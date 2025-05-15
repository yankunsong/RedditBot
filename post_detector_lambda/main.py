import json
import os
import boto3
from reddit_bot import check_and_reply_to_posts, load_environment_variables

# Initialize S3 client outside the handler for connection reuse
s3_client = boto3.client('s3')

# S3 bucket and key for storing data
BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
PROCESSED_POSTS_LOG_KEY = 'processed_posts_log.json'
SUCCESSFUL_QUEUED_MESSAGES_LOG_KEY = 'successful_queued_messages_log.json'

def load_processed_posts_log_from_s3():
    """Load previously processed posts log from S3"""
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=PROCESSED_POSTS_LOG_KEY)
        processed_posts_data = json.loads(response['Body'].read().decode('utf-8'))
        return processed_posts_data
    except s3_client.exceptions.NoSuchKey:
        print(f"No existing file found at s3://{BUCKET_NAME}/{PROCESSED_POSTS_LOG_KEY}. Starting with empty data.")
        return {}
    except Exception as e:
        print(f"Error loading data from S3: {e}")
        return {}

def save_processed_posts_log_to_s3(processed_posts_data):
    """Save processed posts log to S3"""
    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=PROCESSED_POSTS_LOG_KEY,
            Body=json.dumps(processed_posts_data, indent=2),
            ContentType='application/json'
        )
        print(f"Successfully saved data to s3://{BUCKET_NAME}/{PROCESSED_POSTS_LOG_KEY}")
    except Exception as e:
        print(f"Error saving data to S3: {e}")

def load_successful_queued_messages_log_from_s3():
    """Load the log of successfully queued messages from S3."""
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=SUCCESSFUL_QUEUED_MESSAGES_LOG_KEY)
        return json.loads(response['Body'].read().decode('utf-8'))
    except s3_client.exceptions.NoSuchKey:
        print(f"No existing successful queued messages log found at s3://{BUCKET_NAME}/{SUCCESSFUL_QUEUED_MESSAGES_LOG_KEY}. Starting with empty data.")
        return {}
    except Exception as e:
        print(f"Error loading successful queued messages log from S3: {e}")
        return {}

def save_successful_queued_messages_log_to_s3(data):
    """Save the log of successfully queued messages to S3."""
    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=SUCCESSFUL_QUEUED_MESSAGES_LOG_KEY,
            Body=json.dumps(data, indent=2),
            ContentType='application/json'
        )
        print(f"Successfully saved successful queued messages log to s3://{BUCKET_NAME}/{SUCCESSFUL_QUEUED_MESSAGES_LOG_KEY}")
    except Exception as e:
        print(f"Error saving successful queued messages log to S3: {e}")

def lambda_handler(event, context):
    """AWS Lambda handler function"""
    try:
        print("Starting Reddit bot lambda function (SQS direct)...")
        
        credentials = load_environment_variables()
        
        subreddits_raw = os.environ.get('SUBREDDITS', 'testingground4bots')
        subreddits_to_check = [s.strip() for s in subreddits_raw.split(',')]
        print(f"Checking subreddits: {subreddits_to_check}")
        
        processed_posts_log_data = load_processed_posts_log_from_s3()
        successful_queued_messages_log_data = load_successful_queued_messages_log_from_s3()
        
        processed_posts_log_data, successful_queued_messages_log_data, new_messages_queued, log_updated = check_and_reply_to_posts(
            credentials, subreddits_to_check, processed_posts_log_data, successful_queued_messages_log_data
        )
        
        if log_updated:
            save_processed_posts_log_to_s3(processed_posts_log_data)
            print("Updated processed posts log in S3")
        else:
            print("No new posts processed or existing posts updated, no S3 processed log update needed")
        
        if new_messages_queued:
            save_successful_queued_messages_log_to_s3(successful_queued_messages_log_data)
            print("Updated successful queued messages log in S3")
        else:
            print("No new messages queued, successful queued messages log not updated in S3")
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Reddit bot executed successfully, messages sent to SQS.",
                "subreddits_checked": subreddits_to_check,
                "new_messages_queued": new_messages_queued,
                "log_updated": log_updated
            })
        }
    
    except Exception as e:
        print(f"Error in lambda_handler: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "message": f"Error: {str(e)}"
            })
        } 