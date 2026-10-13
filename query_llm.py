from db_utils import db_result, insert_db, update_db
import uuid
import boto3
import json
import re
from user_manager import get_user_role
import ast
import time
from presigned_url_generator import generate_presigned_url_from_s3_uri
from api_activity import send_message_to_connection
from datetime import datetime

def book_appointment(query_input, session_id, connection_id, chat_id, streamed_content):
    reservation_date = query_input['reservation_date']
    reservation_name = query_input['booking_name']
    reservation_time_str = query_input['reservation_time']
    phone_no = query_input['phone_no'] 
    mail_id = query_input['email_id'] 

    # Combine date + time into ISO timestamp
    try:
        combined_datetime = datetime.strptime(
            f"{reservation_date} {reservation_time_str}", "%Y-%m-%d %I:%M %p"
        )
        reservation_time = combined_datetime.isoformat()  # 'YYYY-MM-DDTHH:MM:SS'
    except ValueError as e:
        print("Time parsing error:", e)
        reservation_time = None

    print("Booking details:", reservation_date, reservation_time)

    query = """
        UPDATE "my_sanctuary".dashboard
        SET reservation_time = %s,
            reservation_name = %s,
            phone_no = %s,
            mail_id = %s
        WHERE session_id = %s;
    """
    values = (reservation_time, reservation_name, phone_no, mail_id, session_id)
    update_db(query, values)

    message = f"<start>Appointment booked successfully on {reservation_date} at {reservation_time_str}."

    response = {
        "status_code": 200,
        "output": message
    }
    send_message_to_connection(connection_id, response)

    query_input = {}
    query_input['phone_no'] = phone_no
    query_input['email_id'] = mail_id

    message += connect_live_agent(query_input, session_id, '', connection_id, chat_id, streamed_content, "book_appointment")

    return message

def connect_live_agent(query_input, session_id, user_name, connection_id, chat_id, streamed_content, sync_type = None):
    print("query_input:", query_input)
    phone_no = query_input['phone_no']
    mail_id = query_input['email_id']
    query = """
        UPDATE "my_sanctuary".dashboard
        SET last_activity = now(), connection_id = %s,mail_id = %s, phone_no = %s
        WHERE session_id = %s;"""
    values = (connection_id, mail_id, phone_no, session_id)
    update_db(query, values)
    temp_message = "<start>Connecting to live agent..."
    # if sync_type != "book_appointment":
    #     temp_message = "<end><start>Connecting to live agent..."
    response = {
        "status_code": 200,
        "output": temp_message
    }

    send_message_to_connection(connection_id, response)
    query_llm_invoke_model(session_id, chat_id)
    return "Connecting to live agent..."

def query_llm_invoke_model(session_id, chat_id):
    print("session_id:", session_id)
    bedrock_client = boto3.client('bedrock-runtime', region_name='us-east-1')

    task = "conversation_analysis"

    # Fetch system prompt & tool schemas
    query = f"""
        SELECT prompt_template, bedrock_model
        FROM "my_sanctuary".prompt_template
        WHERE task = '{task}';
    """
    query_info = db_result(query)[0]
    system_prompt = query_info[0]
    model_id = query_info[1]

    model_execution_limit = 0
    query = f"""
        SELECT question, answer, chat_timestamp
        FROM "my_sanctuary".chat_management
        WHERE session_id = '{session_id}'
        ORDER BY chat_timestamp ASC;
    """
    
    list_conversation = db_result(query)

    query = f"""select * from "my_sanctuary".dashboard where session_id = '{session_id}'"""
    session = db_result(query)

    conversations = []
    conversations_str = ""
    if len(session)>0:
        for val in list_conversation:        
            conversations.append({
                "role": "user",
                "content": val[0]
            })
            conversations.append(
            {
                "role": "assistant",
                "content": val[1]
            })
    print("conversation: ", [conversations])            

    while(model_execution_limit<3):
        model_execution_limit = model_execution_limit + 1

        try:
            response = bedrock_client.invoke_model(contentType='application/json', body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 8000,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": system_prompt + "\n\nBelow are the conversations:\n"+str(conversations)},
                        ]
                    }
                ],
            }), modelId=model_id)
            inference_result = response['body'].read().decode('utf-8')
            final = json.loads(inference_result)
            input_tokens = final['usage']['input_tokens']
            output_tokens = final['usage']['output_tokens']
            print("final invoke model:", final)
            text = final['content'][0]['text']
            print("text:", text)

            summary_pattern = r"<summary>([\s\S]*?)<\/summary>"
            sentiment_pattern = r"<sentiment>([\s\S]*?)<\/sentiment>"
            lead_pattern = r"<lead>([\s\S]*?)<\/lead>"

            summary = re.search(summary_pattern, text)
            sentiment = re.search(sentiment_pattern, text)
            lead = re.search(lead_pattern, text)
            summary = summary.group(1).strip() if summary else None
            print("Summary:", summary)
            sentiment = sentiment.group(1).strip() if sentiment else None
            print("Sentiment:", sentiment)
            lead = lead.group(1).strip() if lead else None
            print("Lead:", lead)

            query = """
            update "my_sanctuary".dashboard 
            set summary = %s, sentiment = %s, leads = %s, sentiment_llm_input_token = %s, sentiment_llm_output_token = %s
            where session_id = %s;
            """
            values = (summary, sentiment, lead, input_tokens, output_tokens, session_id)
            update_db(query, values)

            return {
                "status_code": 200,
                "lead": lead,
                "sentiment": sentiment,
                "summary": summary
            }
        except Exception as e:
            print("Excepiton on invoke:", e)
   

def stream_bedrock_to_websocket(model_id, conversation, connection_id,chat_id,streamed_content):
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
    try:
        params = {
            "modelId": model_id,
            "messages": conversation,
        }

        reasoning_text = ""
        final_text = ""
        reference = ""
        status_code = 200
        input_tokens = 0
        output_tokens = 0

        response = bedrock.converse_stream(
                modelId=model_id,
                messages=conversation
            )

        print('reasoning response: ', response)

        result = streamed_content
        current_block = ""
        for chunk in response["stream"]:
            # print("chunk:", chunk)
            temp_text = ""
            if "messageStart" in chunk:
                temp_text = "<end><start>"
                current_block = ""
            
            elif "contentBlockDelta" in chunk:
                delta = chunk["contentBlockDelta"]["delta"]
                if "text" in delta:
                    temp_text = delta["text"]
                    current_block += delta["text"]
            
            elif "contentBlockStop" in chunk:
                temp_text = "<end>"
            
            elif "messageStop" in chunk:
                # message fully complete
                result += current_block
                current_block = ""

            if temp_text:
                send_message_to_connection(connection_id, {
                    "status_code": 200,
                    "output": temp_text
                })

        try:
            input_tokens = chunk['metadata']['usage']['inputTokens']
        except:
            print("No input tokens")
        try:
            output_tokens = chunk['metadata']['usage']['outputTokens']
        except:
            print("No output tokens")
        query = """
            UPDATE "my_sanctuary".chat_management
            SET 
                answer = COALESCE(answer, '') || %s,
                chat_type = 'knowledge_llm',
                kb_input_tokens = COALESCE(kb_input_tokens, 0) + %s,
                kb_output_tokens = COALESCE(kb_output_tokens, 0) + %s
            WHERE chat_id = %s;
        """

        values = (result, input_tokens, output_tokens, chat_id)
        # print('values:',[values])
        update_db(query,values)
        # response = {
        #         "status_code": 200,
        #         "output": "<end>"
        #     }
        # send_message_to_connection(connection_id, response)
        return result

    except Exception as e:
        print("Error during streaming:", str(e))
        
        response = {
            "status_code": status_code,
            "answer": answer,
            "reference": output
        }

        print('streaming response', response)
        send_message_to_connection(connection_id, response)
        return None


def format_conversation(conversation_list):
    return "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in conversation_list])

def get_knowledge_base_response(conversation, session_id, connection_id, chat_id, streamed_content):
    response = {
        "status_code": 200,
        "output": "<start>Accessing knowledge..."
    }
    send_message_to_connection(connection_id, response)

    status_code = 200
    # try:
    # Step 1: Fetch KB + Model details
    query = """
        SELECT prompt_template, knowledgebase_id, model_arn, bedrock_model
        FROM "my_sanctuary".prompt_template 
        WHERE task = 'SkinStation_KB';
    """
    query_info = db_result(query)[0]
    knowledge_base_id = query_info[1]
    model_arn = query_info[2]
    model_id = query_info[3]
    prompt_template = query_info[0]

    bedrock_client = boto3.client('bedrock-agent-runtime', region_name='us-east-1')

    # Step 2: Get KB session ID (if exists)
    query = f"""
        SELECT kb_session_id
        FROM "my_sanctuary".dashboard 
        WHERE session_id = '{session_id}';
    """
    kb_session_query = db_result(query)
    kb_session_id = kb_session_query[0][0] if kb_session_query and kb_session_query[0] and kb_session_query[0][0] else None

    # Step 3: Retrieve context (not generate)
    retrieve_params = {
        "knowledgeBaseId": knowledge_base_id,
        "retrievalQuery": {
            "text": conversation
        }
    }

    # Include existing KB session if any
    if kb_session_id:
        retrieve_params["sessionId"] = kb_session_id

    print("Retrieving from KB...")
    retrieve_response = bedrock_client.retrieve(**retrieve_params)
    print('retrieve_response:', retrieve_response)

    # Update new kb_session_id if returned
    if "sessionId" in retrieve_response:
        new_kb_session_id = retrieve_response["sessionId"]
        query = """
            UPDATE "my_sanctuary".dashboard
            SET kb_session_id = %s
            WHERE session_id = %s;
        """
        update_db(query, (new_kb_session_id, session_id))

    # Step 4: Extract retrieved knowledge
    references = []
    retrieved_text = ""
    try:
        retrieved_references = retrieve_response.get("retrievalResults", [])
        for ref in retrieved_references:
            content = ref["content"]["text"]
            retrieved_text += f"\n{content}"
            if "location" in ref and "s3Location" in ref["location"]:
                presigned = generate_presigned_url_from_s3_uri(ref["location"]["s3Location"]["uri"])
            else:
                presigned = "N/A"
            references.append({"content": content, "location": presigned})
    except Exception as e:
        print("No valid references found.", e)
        references = "No Reference found."

    # Step 5: Prepare conversation for streaming
    # Combine user question + retrieved KB info
    conversations_str = [
        {
            "role": "user",
            "content": [{
                "text": f"{prompt_template}\nUse the following knowledge to answer:\n{retrieved_text}\n\nQuestion: {conversation}"
            }]
        }
    ]

    # Step 6: Stream final answer through Bedrock (Claude, Nova, etc.)
    print("Starting Bedrock stream...")
    answer = stream_bedrock_to_websocket(
        model_id=model_id,
        conversation=conversations_str,
        connection_id=connection_id,
        chat_id = chat_id,
        streamed_content = streamed_content
    )

    return answer

    # except Exception as e:
    #     print("Error:", str(e))
    #     error_response = {
    #         "status_code": 500,
    #         "answer": "Internal server error. Try after some time.",
    #         "reference": str(e)
    #     }
    #     send_message_to_connection(connection_id, error_response)
    #     return "Internal server error. Try after some time."
        

def get_date_with_suffix(day: int) -> str:
    """Return day number with English ordinal suffix (e.g., 1st, 2nd, 3rd, 4th...)."""
    if 11 <= day <= 13:
        return f"{day}th"
    match day % 10:
        case 1: return f"{day}st"
        case 2: return f"{day}nd"
        case 3: return f"{day}rd"
        case _: return f"{day}th"

def monitor_agent(message_history, user_name, session_id, connection_id, conversations_str, chat_id):
    client = boto3.client('bedrock-runtime', region_name='us-east-1' )

    task = "live_agent"

    # Fetch system prompt & tool schemas
    query = f"""
        SELECT prompt_template, bedrock_model, answerformat
        FROM "my_sanctuary".prompt_template
        WHERE task = '{task}';
    """

    current_timestamp = datetime.now()
    day_with_suffix = get_date_with_suffix(current_timestamp.day)
    formatted_timestamp = current_timestamp.strftime(f"%A, {day_with_suffix} %B %Y")

    current_date = f"Today's date: {formatted_timestamp}\n\n"
    
    query_info = db_result(query)[0]
    system_prompt = query_info[0].replace("{{current_date}}", current_date)
    model_id = query_info[1]
    tool_schemas = ast.literal_eval(query_info[2])

    # try:
    # Validate messages
    valid_messages = []
    for msg in message_history:
        if isinstance(msg.get('content'), str) and msg['content'].strip():
            valid_messages.append(msg)
        elif isinstance(msg.get('content'), list):
            content_list = [c for c in msg['content'] if c.get('text', '').strip()]
            if content_list:
                msg['content'] = content_list
                valid_messages.append(msg)

    if not valid_messages:
        return "No valid messages to process", ""

    # Call Bedrock
    response = client.invoke_model_with_response_stream(
        contentType='application/json',
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "temperature": 0,
            "system": system_prompt,
            "tools": tool_schemas,
            "messages": valid_messages
        }),
        modelId=model_id
    )

    # Process the streamed response
    streamed_content = ''
    content_block = None
    action_content = ''
    assistant_response = []
    tool_usage = False
    input_tokens = 0
    output_tokens = 0

    for item in response['body']:
        temp_message = ""
        content = json.loads(item['chunk']['bytes'].decode())
        # print('content:', content)
        try:
            input_tokens = content['message']['usage']['input_tokens']
        except:
            print("No input tokens")

        try:
            output_tokens = content['usage']['output_tokens']
        except:
            print("No output tokens")

        if content['type'] == 'content_block_start':
            content_block = content['content_block']

        elif content['type'] == 'content_block_delta':
            if content['delta']['type'] == 'text_delta':
                streamed_content += content['delta']['text']
                temp_message = content['delta']['text']
            elif content['delta']['type'] == 'input_json_delta':
                action_content += content['delta']['partial_json']

        elif content['type'] == 'content_block_stop':
            if content_block['type'] == 'text':
                content_block['text'] = streamed_content
                assistant_response.append(content_block)
            elif content_block['type'] == 'tool_use':
                try:
                    content_block['input'] = json.loads(action_content) if action_content else {}
                except json.JSONDecodeError:
                    print(f"Error parsing tool input: {action_content}")
                    content_block['input'] = {}
                assistant_response.append(content_block)

            temp_message += "<end>"

        # Optional streaming to connection
        if content['type'] in ['content_block_delta', 'content_block_stop']:
            response_obj = {
                "status_code": 200,
                "output": f"<start>{temp_message}" if content['type'] == 'content_block_start' else temp_message
            }
            send_message_to_connection(connection_id, response_obj)

    tool_response = ""

    # Process tool calls
    for action in assistant_response:
        print('action:', action)
        if action['type'] == 'tool_use':
            if action['name'] == 'get_knowledge_base_response':
                streamed_content += get_knowledge_base_response(str(message_history), session_id, connection_id, chat_id, streamed_content)
                # tool_usage = True
            elif action['name'] == 'connect_live_agent':
                streamed_content += connect_live_agent(action['input'], session_id, user_name, connection_id, chat_id, streamed_content)
                tool_response = streamed_content
                # tool_usage = True
            elif action['name'] == 'book_appointment':
                tool_response += book_appointment(action['input'], session_id, connection_id, chat_id, streamed_content)
                streamed_content = tool_response
                # tool_usage = True
            message_history.append({
                'role': 'user',
                'content': [{
                    "type": "tool_result",
                    "tool_use_id": action['id'],
                    "content": [{"type": "text", "text": tool_response}]
                }]
            })
    if tool_usage == False:
        unanswered_chat = ""
        if "I'm sorry, I don't have that information" in streamed_content:
            unanswered_chat = " ,unanswered_chat = COALESCE(unanswered_chat, 0) + 1 "
        query = f"""
            UPDATE "my_sanctuary".chat_management
            SET 
                answer = COALESCE(answer, '') || %s
                {unanswered_chat},
                chat_type = 'agent',
                input_token = %s,
                output_token = %s,
                refering_input_data = %s
            WHERE chat_id = %s;
        """
        values = (streamed_content, input_tokens, output_tokens, system_prompt + str(valid_messages) + str(tool_schemas), chat_id)
        update_db(query, values)

    # except Exception as e:
    #     streamed_content = str(e)
    #     print('Exception on tool calling:', e)
    #     response_obj = {
    #         "status_code": 200,
    #         "output": "<start>Internal server error. Try after some time.<end>"
    #     }
    #     if len(connection_id) > 0:
    #         send_message_to_connection(connection_id, response_obj)

    return streamed_content

def query_agent(connection_id, session_id, question, user_name):

    answer = "The question you asked doesn't align with the supported topics. We've stopped processing the query. Please try again later with a more relevant one."

    query = f"""
        SELECT question, answer
        FROM (
            SELECT question, answer, chat_timestamp
            FROM "my_sanctuary".chat_management
            WHERE session_id = '{session_id}'
            ORDER BY chat_timestamp DESC
        ) AS sub
        ORDER BY chat_timestamp ASC;
    """
    
    list_conversation = db_result(query)

    query = f"""select * from "my_sanctuary".dashboard where session_id = '{session_id}'"""
    session = db_result(query)

    conversations = []
    conversations_str = ""
    if len(session)>0:
        for val in list_conversation:
            # print('list_conversations:', val)
        
            conversations.append({
                "role": "user",
                "content": val[0]
            })
            conversations.append(
            {
                "role": "assistant",
                "content": val[1]
            })
    else:
        status = "Inquiring"
        query = """
            INSERT INTO "my_sanctuary".dashboard
            (session_id, user_name, task_status, last_activity, connection_id)
            VALUES(%s, %s, %s, now(), %s);
        """   
        
        values = (session_id, user_name, 'unassigned', 'Unrequested')
        # print(values)
        insert_db(query,values)
        initial_response = f"Hello {user_name}! How can I help you today?"
        query = """
        INSERT INTO "my_sanctuary".chat_management
        (chat_id, session_id, answer, chat_timestamp, user_name)
        VALUES(%s, %s, %s, now(), %s);
        """   
        chat_id = str(uuid.uuid4())
        values = (chat_id, session_id, initial_response, user_name)
        # print('values:',[values])
        insert_db(query,values)

    conversations.append(
        {
                "role": "user",
                "content": question
        }
    )
    conversations_str+= f"user: {question}\n"
    # print('query_text:', conversations)
    chat_id = str(uuid.uuid4())
    query = """
        INSERT INTO "my_sanctuary".chat_management
        (chat_id, session_id, question, chat_timestamp, user_name)
        VALUES(%s, %s, %s, now(), %s);
    """   
    values = (chat_id, session_id, question, user_name)
    # print('values:',[values])
    insert_db(query,values)

    answer = monitor_agent(conversations, user_name, session_id, connection_id, conversations_str, chat_id)
    print('tool_call:',answer)

def query_live_agent(connection_id, session_id, question):
    chat_id = str(uuid.uuid4())
    query = """
        INSERT INTO "my_sanctuary".chat_management
        (chat_id, session_id, question, chat_timestamp)
        VALUES(%s, %s, %s, now());
    """   
    values = (chat_id, session_id, question)
    print('values:',[values])
    insert_db(query,values)

    agent_connection_id = None

    query = f"""
        SELECT agent_connection_id
        FROM "my_sanctuary".dashboard 
        WHERE session_id = '{session_id}';
    """
    query_info = db_result(query)
    print('query_info:', query_info)
    
    if len(query_info) > 0:
        agent_connection_id = query_info[0][0]
        if agent_connection_id:
            response = {
                "status_code": 200,
                "output": question,
                "chat_id": chat_id
        }
            print('response:',response)
            send_message_to_connection(agent_connection_id, response)            

def answer_user(connection_id, session_id, query_response):
    query_response = f"<start>{query_response}<end>"
    query = f"""
        SELECT chat_id, answer from "my_sanctuary".chat_management 
        where session_id = '{session_id}' 
        order by chat_timestamp desc
        limit 1"""
    
    result = db_result(query)
    chat_id = None
    if len(result)>=1:
        chat_id = result[0][0]

    query = f"""
        SELECT connection_id
        FROM "my_sanctuary".dashboard 
        WHERE session_id = '{session_id}';
    """
    query_info = db_result(query)
    print('query_info:', query_info)
    answer = ""
    new_message = False
    user_connection_id = None
    if len(query_info)>0:
        user_connection_id = query_info[0][0]
        answer = result[0][1]

        if "An agent has connected" in answer:
            new_message = True
            query_response = "<end>" + query_response

    # if user_connection_id:
    #     response = {
    #             "status_code": 200,
    #             "output": "<end>" 
    #     }
    #     print('response:',response)
    #     send_message_to_connection(user_connection_id, response)

    query = """
        UPDATE "my_sanctuary".dashboard
        SET agent_connection_id = %s
        WHERE session_id = %s;
    """
    values = (connection_id, session_id)
    update_db(query, values)


    if new_message:
        chat_id = str(uuid.uuid4())
        query = """
            INSERT INTO "my_sanctuary".chat_management
            (chat_id, session_id, answer, chat_timestamp)
            VALUES(%s, %s, %s, now());
        """   
        values = (chat_id, session_id, query_response)
        print('values:',[values])
        insert_db(query,values)
    else:
        query = """
            UPDATE "my_sanctuary".chat_management
            SET answer = COALESCE(answer, '') || %s
            WHERE chat_id = %s;
        """
        values = (query_response, chat_id)
        update_db(query, values)

    if user_connection_id:
        response = {
                "status_code": 200,
                "output": query_response 
        }
        print('response:',response)
        send_message_to_connection(user_connection_id, response)

