import boto3
import mimetypes
import os
from urllib.parse import urlparse
bucket = "skin-station-ai-chatbot-data-storage"

def sanitize_filename(filename):
    # Replace characters not supported by ISO-8859-1
    return filename.encode('ascii', 'ignore').decode('ascii')

def generate_presigned_url_from_s3_uri(s3_uri, expiration=3600):
    parsed_uri = urlparse(s3_uri)
    key = parsed_uri.path.lstrip('/')
    
    s3_client = boto3.client('s3', region_name='us-east-1')
    
    mime_type, _ = mimetypes.guess_type(key)
    
    # Extract and sanitize the filename only
    original_filename = os.path.basename(key)
    safe_filename = sanitize_filename(original_filename)
    
    try:
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': bucket,
                'Key': key,
                'ResponseContentType': mime_type or 'application/octet-stream',
                'ResponseContentDisposition': f'inline; filename="{safe_filename}"'
            },
            ExpiresIn=expiration
        )
        return presigned_url
    except Exception as e:
        print(f"Error generating pre-signed URL: {e}")
        return None