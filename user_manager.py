import boto3, os
from db_utils import db_result, delete_db, insert_db, update_db
import boto3

def get_user_role(user_name):
    query = f"""SELECT user_type
                FROM "my_sanctuary".user_management where user_name = '{user_name}';"""
    query_info = db_result(query)
    print('get_user_role:',query_info)
    if query_info:
        query_info = query_info[0]
        return query_info[0] or "user"
    else:
        return "user not found"


def register_user(user_id, user_name, password, user_type):
    try:

        UserAttributes=[
                {
                    'Name': 'email_verified',
                    'Value': 'true'
                },
                {
                    'Name': 'profile',
                    'Value': user_type
                },
                {
                    'Name': 'email',
                    'Value': user_name
                }
            ]
        # Register user in Cognito
        cognito_client = boto3.client('cognito-idp', 'ap-southeast-1')

        user_pool_id = os.environ['user_pool_id']
        temporary_password = password
        permanent_password = password

        response = cognito_client.admin_create_user(  
            UserPoolId=user_pool_id,
            Username=user_name,
            TemporaryPassword=temporary_password,
            UserAttributes=UserAttributes,
            MessageAction='SUPPRESS'  
        )
        print(f"User {user_name} created successfully.")
    
        cognito_client.admin_set_user_password(
            UserPoolId=user_pool_id,
            Username=user_name,
            Password=permanent_password,  
            Permanent=True  
        )
        print(f"Permanent password set for user {user_name}.")
        
        # Insert user into database
        query = """
            INSERT INTO "my_sanctuary".user_management
            (user_id, user_name, password, created_at, user_type)
            VALUES(%s, %s, %s, now(), %s);
        """
        values = (
            user_id,
            user_name,
            password,
            user_type
        )
        
        insert_db(query, values)
        
        return {
            "statusCode": 200,
            "result": "User registered successfully"
        }
    
    except Exception as e:
        print('Exception on register user:', e)
        return {
            "statusCode": 500,
            "result": f"Unable to register user : {e}"
        }

def unregister_user(user_name):
    status_code = 200
    result = "User unregistered successfully"

    try:
        # Delete user from Cognito
        cognito_client = boto3.client('cognito-idp', 'ap-southeast-1')
        cognito_client.admin_delete_user(
            UserPoolId=os.environ['user_pool_id'],
            Username=user_name
        )

        # Delete user from database
        query = """
            DELETE FROM "my_sanctuary".user_management
            WHERE user_name = %s;
        """
        values = (user_name,)
        delete_db(query, values)
    except Exception as e:
        print('Exception on unregister user:', e)
        result = "Unable to unregister user."
        status_code = 500

    return {
        "statusCode": status_code,
        "result": result
    }


def list_user(keyword, user_name, page_no, page_size):
    
    role = get_user_role(user_name)
    query = f"""
    SELECT user_id, user_name, created_at, user_type
    FROM "my_sanctuary".user_management u
    WHERE ("user_name" ILIKE '%{keyword}%'
    OR "user_type" ILIKE '%{keyword}%')
    """

    query +="""
    order by user_name;
    """
    print('role:', role)
    print('list _user qeury:', query)
    query_info = db_result(query)
    print('list_usr:', query_info)
    status_code = 200
    output = []
    if query_info:
        for val in query_info:
            temp_json = {
                "user_id": val[0],
                "user_name": val[1],
                "created_at": str(val[2]),
                "user_type": val[3]
            }
            output.append(temp_json)
    
    return {
        "statusCode": status_code,
        "result": output
    }

def edit_user(user_id, updates=None):
    updates = updates or {} 
    status_code = 200
    result = "User updated successfully"
    allowed_fields = [
        'password', 'ivanti_username', 'ivanti_password', 'user_type', 'team_lead', 'domain'
    ]
    try:
        set_clauses = []
        values = []
        # Handle password update in Cognito and DB
        if 'password' in updates:
            # Update password in Cognito
            cognito_client = boto3.client('cognito-idp', 'ap-southeast-1')
            user_pool_id = os.environ['user_pool_id']
            # Get user_name from DB
            query = 'SELECT user_name FROM "my_sanctuary".user_management WHERE user_id = %s;'
            user_name_result = db_result(query, (user_id,))
            if user_name_result:
                user_name = user_name_result[0][0]
                cognito_client.admin_set_user_password(
                    UserPoolId=user_pool_id,
                    Username=user_name,
                    Password=updates['password'],
                    Permanent=True
                )
            set_clauses.append('password = %s')
            values.append(updates['password'])
        # Handle other allowed fields
        for key in allowed_fields:
            if key != 'password' and key in updates:
                set_clauses.append(f"{key} = %s")
                values.append(updates[key])
        if set_clauses:
            query = f"""
                UPDATE "my_sanctuary".user_management
                SET {', '.join(set_clauses)}
                WHERE user_id = %s;
            """
            values.append(user_id)
            update_db(query, tuple(values))
    except Exception as e:
        print('Exception on edit user:', e)
        result = f"Unable to update user: {e}"
        status_code = 500
    return {
        "statusCode": status_code,
        "result": result
    }
    