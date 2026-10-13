from datetime import timezone, timedelta
from datetime import datetime
import pandas as pd
from user_manager import get_user_role
from db_utils import db_result
import io, uuid
import boto3
s3_bucket  = "skin-station-ai-chatbot-data-storage"

def generate_report(start_date_str, end_date_str, user_name, keyword=""):
    
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date   = datetime.strptime(end_date_str,   "%Y-%m-%d") + timedelta(days=1)
    print('start_date:', start_date, " end_date:", end_date)

    user_role = get_user_role(user_name)
    if user_role == "user not found":
        raise Exception("Invalid user")

    # --- Build queries based on user role ---
    if user_role == "team_lead":
        chat_query = """
            SELECT d.session_id, d.chat_type, d.phone_number, d.mail_id, d.status, d.last_activity, d.user_name
            FROM \"my_sanctuary\".dashboard d
            WHERE d.user_name = %s and d.keyword ILIKE %s
        """
        chat_data = db_result(chat_query, (user_name, keyword))
    else:
        chat_query = """
            SELECT d.session_id, d.chat_type, d.status, d.last_activity, d.user_name
            FROM \"my_sanctuary\".dashboard d
            WHERE d.keyword ILIKE %s
        """
        chat_data = db_result(chat_query, (keyword,))

    chat_df = pd.DataFrame(chat_data, columns=["session_id", "chat_type", "phone_number", "mail_id", "status", "last_activity", "user_name"])
    # Remove timezone info if present
    if "last_activity" in chat_df.columns:
        chat_df["last_activity"] = pd.to_datetime(chat_df["last_activity"]).dt.tz_localize(None)

    # --- Generate Excel ---
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        chat_df.to_excel(writer, sheet_name="Chat Report", index=False)
    output.seek(0)

    # --- Upload to S3 ---
    s3 = boto3.client("s3", region_name="us-east-1")
    s3_key = f"reports/Ivanti_Report_{start_date_str}_{end_date_str}_{uuid.uuid4().hex}.xlsx"

    s3.upload_fileobj(
        Fileobj=output,
        Bucket=s3_bucket,
        Key=s3_key,
        ExtraArgs={
            "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "ContentDisposition": f'attachment; filename="Ivanti_Report_({start_date_str})-({end_date_str}).xlsx"'
        }
    )

    # --- Generate Pre-Signed URL ---
    presigned_url = s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": s3_bucket, "Key": s3_key},
        ExpiresIn=3600
    )

    # --- Return Response ---
    return {
        "statusCode": 200,
        "message": f"Report generated for: {start_date_str} to {end_date_str}",
        "download_url": presigned_url
    }