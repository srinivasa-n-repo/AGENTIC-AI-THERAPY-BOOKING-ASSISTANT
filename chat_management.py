from user_manager import get_user_role
from db_utils import db_result, update_db, insert_db
from datetime import timezone, timedelta
import uuid
from api_activity import send_message_to_connection

def get_session_conversation(session_id):
    
    query = f"""
        SELECT question, answer, chat_timestamp, user_name
        FROM "my_sanctuary".chat_management
        where session_id  = '{session_id}'
        order by chat_timestamp;     
    """
    individual_conversations = db_result(query)
    print('overall individual_conversations', individual_conversations)
    overall_conversations = []
    if len(individual_conversations)>0:
        for conversation in individual_conversations:
            temp_data = {
                f"{conversation[3]}": (conversation[0] or "").replace("<start>", "").replace("<end>", ""),
                "answer": (conversation[1] or "").replace("<start>", "").replace("<end>", ""),
                "time_stamp": str(conversation[2])
            }

            overall_conversations.append(temp_data)
    
    print("session_conv:", overall_conversations)
    return {
        "statusCode": 200,
        "result": overall_conversations
    }

def list_user_session(keyword, date, user_name, chat_type, page_no, page_size):
    print('called list_user_session')
    status_code = 200
    UTC = timezone.utc
    IST = timezone(timedelta(hours=5, minutes=30))

    keyword = keyword or ''
    date = date or ''
    user_name = user_name or ''
    page_no = int(page_no or 1)
    page_size = int(page_size or 10)
    offset = (page_no - 1) * page_size

    user_role = get_user_role(user_name)

    # Handle date filters
    start_date = end_date = ""
    if date:
        if isinstance(date, list) and len(date) > 1:
            start_date, end_date = date[0], date[1]
        else:
            start_date = end_date = date

    # Map chat type
    chat_type_mapping = {
        "open_task": "Open Task",
        "closed_task": "Closed Task",
        "unassigned": "unassigned"
    }
    chat_type_value = chat_type_mapping.get(chat_type, chat_type)
    print("chat_type_value:", chat_type_value)

    # ----------------------------
    # Build filters dynamically
    # ----------------------------
    filters = "WHERE 1=1"
    total_filters = filters
    date_filter = ""

    if keyword.strip():
        filters_value = f"""
        AND (
            d.user_name ILIKE '%{keyword}%' OR
            d.status ILIKE '%{keyword}%' OR
            d.subject ILIKE '%{keyword}%' OR
            d.task_status ILIKE '%{keyword}%' OR
            d.session_id ILIKE '%{keyword}%' OR
            d.agent_name ILIKE '%{keyword}%' OR
            d.mail_id ILIKE '%{keyword}%' OR
            d.phone_no ILIKE '%{keyword}%'
        )
        """
        filters += filters_value
        total_filters += filters_value

    if start_date and end_date:
        filters_value = f" AND d.last_activity >= '{start_date} 00:00:00' AND d.last_activity <= '{end_date} 23:59:59'"
        filters += filters_value
        total_filters += filters_value
        date_filter = f" chat_timestamp >= '{start_date} 00:00:00' AND chat_timestamp <= '{end_date} 23:59:59'"

    if chat_type_value != 'all_chats':
        filters += f" AND d.task_status ILIKE '%{chat_type_value}%'"

    if user_role != "admin":
        filters_value = f" AND (d.agent_name ILIKE '%{user_name}%' AND d.agent_name IS NOT NULL AND d.agent_name ! '')"
        filters += filters_value
        total_filters += filters_value

    # ----------------------------
    # Main Data Query (fixed)
    # ----------------------------
    base_query = f"""
        SELECT
            d.session_id,
            d.task_status,
            d.subject,
            d.last_activity,
            d.user_name,
            d.agent_name,
            d.mail_id,
            d.phone_no,
            d.connection_id,
            d.reservation_time,
            d.summary,
            d.sentiment,
            d.leads,
            COUNT(cm.unanswered_chat) AS count_answered,
            d.reservation_name
        FROM "my_sanctuary".dashboard d
        LEFT JOIN "my_sanctuary".chat_management cm
            ON d.session_id = cm.session_id
        {filters}
        GROUP BY
            d.session_id, d.task_status, d.subject, d.last_activity, d.user_name,
            d.agent_name, d.mail_id, d.phone_no, d.connection_id, d.reservation_time,
            d.summary, d.sentiment, d.leads, d.reservation_name
        ORDER BY d.last_activity DESC
        LIMIT {page_size}
        OFFSET {offset}
    """

    print('list_user_session query:', [base_query])

    user_sessions = db_result(base_query)
    print("user_sessions:", user_sessions)

    output = []
    if user_sessions:
        for val in user_sessions:
            timestamp = val[3]
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            ist_time = timestamp.astimezone(IST)
            output.append({
                "session_id": val[0],
                "chat_type": val[1],
                "subject": val[2],
                "time_stamp": str(ist_time.isoformat() if ist_time else None),
                "user_name": val[4],
                "agent_name": val[5],
                "mail_id": val[6],
                "phone_no": val[7],
                "connection_id": val[8],
                "reservation_date": str(val[9]),
                "summary": val[10],
                "sentiment": val[11],
                "leads": val[12],
                "count_answered": val[13],
                "reservation_name": val[14]
            })

    # ----------------------------
    # Total Records
    # ----------------------------
    total_query = f"""
        SELECT
            COUNT(*) FILTER (WHERE task_status ILIKE '%Open Task%') AS open_task,
            COUNT(*) FILTER (WHERE task_status ILIKE '%Closed Task%') AS closed_task,
            COUNT(*) FILTER (WHERE task_status ILIKE '%unassigned%') AS unassigned,
            COUNT(*) AS total_task
        FROM "my_sanctuary".dashboard d
        {total_filters}
    """

    result = db_result(total_query)

    # ----------------------------
    # Unanswered / Question Count
    # ----------------------------
    query = """
        SELECT COUNT(question), COUNT(unanswered_chat)
        FROM "my_sanctuary".chat_management
    """
    if len(date_filter) > 0:
        query += f" WHERE {date_filter}"

    card_info = db_result(query)
    question_count = card_info[0][0] if card_info else 0
    unanswered_chat = card_info[0][1] if card_info else 0

    # ----------------------------
    # Reservation & Active Connection
    # ----------------------------
    reservation_query = f"""
        SELECT COUNT(reservation_time)
        FROM "my_sanctuary".dashboard d
        {filters}
    """
    reservation_info = db_result(reservation_query)
    reservation_count = reservation_info[0][0] if reservation_info else 0

    active_query = f"""
        SELECT COUNT(connection_id)
        FROM "my_sanctuary".dashboard d
        {filters}
        AND d.connection_id NOT IN ('Unrequested', 'disconnected', '')
        AND d.connection_id IS NOT NULL
    """
    print("active query:", [active_query])
    active_info = db_result(active_query)
    active_connection = active_info[0][0] if active_info else 0

    # ----------------------------
    # Final Response
    # ----------------------------
    total_records = {
        "open_task": result[0][0] if result else 0,
        "closed_task": result[0][1] if result else 0,
        "unassigned": result[0][2] if result else 0,
        "total_task": result[0][3] if result else 0,
        "unanswered_chat": unanswered_chat,
        "question_count": question_count,
        "reservation_count": reservation_count,
        "active_connection": active_connection
    }

    return {
        "status_code": status_code,
        "total_records": total_records,
        "output": output
    }

def get_user_chat(user_id):

    query = f"""
        SELECT chat_id, question, answer, chat_timestamp
        FROM "my_sanctuary".chat_management
        WHERE user_id = '{user_id}'
        ORDER BY chat_timestamp DESC;
    """
    
    chat_history = db_result(query)
    output = []
    if chat_history:
        for chat in chat_history:
            temp_json = {
                "chat_id": chat[0],
                "question": chat[1].replace('<start>','').replace('<end>',''),
                "answer": chat[2].replace('<start>','').replace('<end>',''),
                "timestamp": str(chat[3])
            }
            output.append(temp_json)

    return {
        "statusCode": 200,
        "result": output
    }

def update_task_status(agent_name, session_id, task_status, user_connection_id):
    print("task_status:", task_status)

    # ✅ Step 1: Check if a live agent is already connected
    if task_status != "Closed Task":
        check_query = """
            SELECT live_agent_connected
            FROM "my_sanctuary".dashboard
            WHERE session_id = %s;
        """
        existing_status = db_result(check_query, (session_id,))

        if existing_status and existing_status[0][0] == 1:
            return {
                "statusCode": 200,
                "result": "Another agent is already connected."
            }

    # ✅ Step 2: Determine live_agent_connected flag
    live_agent_connected = 1 if task_status == "Open Task" else 0

    # ✅ Step 3: Update dashboard
    query = """
        UPDATE "my_sanctuary".dashboard
        SET live_agent_connected = %s, task_status = %s, agent_name = %s, connection_id = %s
        WHERE session_id = %s;
    """
    values = (live_agent_connected, task_status, agent_name, user_connection_id, session_id)
    update_db(query, values)

    # ✅ Step 4: Prepare response message
    chat_id = str(uuid.uuid4())
    if task_status == "Closed Task":
        answer = "<start>The agent has ended the chat. You can still query the knowledge base if you need more information.<end>"
    else:
        answer = "<start>An agent has connected. Please hold on for a moment."

    # ✅ Step 5: Log chat message
    insert_query = """
        INSERT INTO "my_sanctuary".chat_management
        (chat_id, session_id, question, answer, chat_timestamp)
        VALUES (%s, %s, %s, %s, now());
    """
    insert_values = (chat_id, session_id, '', answer)
    insert_db(insert_query, insert_values)

    # ✅ Step 6: Notify user if connection_id available
    if user_connection_id:
        response = {
            "status_code": 200,
            "output": f"{answer}"
        }
        print('response:', response)
        send_message_to_connection(user_connection_id, response)

    # ✅ Step 7: Return success
    return {
        "statusCode": 200,
        "result": "Task status updated successfully."
    }
