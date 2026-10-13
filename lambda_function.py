from user_manager import register_user, unregister_user, list_user, edit_user
from chat_management import list_user_session, get_user_chat, get_session_conversation, update_task_status
from report_generator import generate_report
from query_llm import query_agent, query_live_agent, answer_user, query_llm_invoke_model
import json
from db_utils import db_result

def lambda_handler(event, context):
    # TODO implement
    print("Event Received:", event)
    
    try:        
        connection_id = event['requestContext']['connectionId']
        event = json.loads(event['body'])
    except Exception as e:
        connection_id = None
    print('event:', event)
    section = event.get("section")
    event_type = event.get("event_type")


    if section == "user_management":
        if event_type == "register":
            user_id = event['user_id']
            user_name = event['user_name']
            password = event['password']
            user_type = event['user_type']
            return register_user(user_id, user_name, password, user_type)
        elif event_type == "unregister":
            user_name = event['user_name']
            return unregister_user(user_name)
        
        elif event_type == "list_user":
            keyword = event.get('keyword').strip()
            user_name = event.get('user_name').strip()
            page_no = int(event.get('page_no', 1))
            page_size = int(event.get('limit', 10))
            list_user_response = list_user(keyword, user_name, page_no, page_size)
            return list_user_response
        
        elif event_type == "edit_user":
            user_id = event['user_id']
            new_data = event['new_data']
            # Call the function to edit user
            edit_user_response = edit_user(user_id, new_data)
            return edit_user_response
        
        elif event_type == "list_user":
            keyword = event.get('keyword').strip()
            user_name = event.get('user_name').strip()
            page_no = int(event.get('page_no', 1))
            page_size = int(event.get('limit', 10))
            list_user_response = list_user(keyword, user_name, page_no, page_size)
            return list_user_response
        
    if section == "chat_section":

        if event_type == "get_session_conversation":
            session_id = event['session_id']
            overall_conversations = get_session_conversation(session_id)
            return overall_conversations

        elif event_type == "list_user_session":
            print("Entered list_user_session")
            keyword = event.get('keyword', '') or ''
            date = event.get('date', '')
            user_name = event.get('user_name', '')
            chat_type = event.get('chat_type', 'all_chats')
            page_no = int(event.get('page_no', 1))
            page_size = int(event.get('limit', 10))

            list_user_sessions = list_user_session(keyword, date, user_name, chat_type, page_no, page_size)
            return list_user_sessions
        
        elif event_type == "get_user_chat":
            user_id = event['user_id']
            # Call the function to get user chat
            user_chat = get_user_chat(user_id)
            return user_chat

        elif event_type == "generate_report": 
            start_date_str, end_date_str = event["date"]
            user_name = event['user_name']
            return generate_report(start_date_str, end_date_str, user_name)
        
        elif event_type == "task_update":
            agent_name = event['agent_name']
            session_id = event['session_id']
            task_status = event['task_status']
            user_connection_id = event['user_connection_id']
            # Call the function to update task status
            update_response = update_task_status(agent_name, session_id, task_status, user_connection_id)
            return update_response

    if section == "chatbot":
        session_id = str(event['session_id'])
        query = f"""
        SELECT cm.answer
        FROM "my_sanctuary".chat_management cm
        JOIN "my_sanctuary".dashboard d
            ON cm.session_id = d.session_id
        WHERE cm.answer ILIKE '%Connecting to live agent...%'
        AND d.live_agent_connected = 1
        AND cm.session_id = '{session_id}';
        """
        print('query:', [query])
    
        connection_status = db_result(query)
        print('connection_status:', [connection_status])
        if len(connection_status) >= 1 and event_type!="answer_user":
            event_type = "query_live_agent"
            
        if event_type == "query_live_agent":
            try:
                lenght = len(connection_status[0])
            except:
                event_type = 'query_agent'

        print('event_type of chatbot:', event_type)

        if event_type == "query_agent":
            question = event['query']
            user_name = event['user_name']
            query_agent(connection_id, session_id, question, user_name)

        if event_type == "query_live_agent":
            question = event['query']
            user_name = event['user_name']
            query_live_agent(connection_id, session_id, question)

        if event_type == "answer_user":
            query_response = event['query_response']
            answer_user(connection_id, session_id, query_response)

        if event_type == "query_llm_invoke_model":
            session_id = event['session_id']
            chat_id = ""
            return query_llm_invoke_model(session_id, chat_id)



       
        