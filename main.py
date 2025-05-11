import json
import os
import boto3
from reddit_bot import check_and_reply_to_posts, load_environment_variables

# Initialize S3 client outside the handler for connection reuse
s3_client = boto3.client('s3')

# S3 bucket and key for storing replied posts data
BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
PROCESSED_POSTS_LOG_KEY = 'processed_posts_log.json'
SUCCESSFUL_REPLIES_LOG_KEY = 'successful_replies_log.json'

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

def load_successful_replies_log_from_s3():
    """Load the log of successfully replied posts from S3."""
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=SUCCESSFUL_REPLIES_LOG_KEY)
        return json.loads(response['Body'].read().decode('utf-8'))
    except s3_client.exceptions.NoSuchKey:
        print(f"No existing successful replies log found at s3://{BUCKET_NAME}/{SUCCESSFUL_REPLIES_LOG_KEY}. Starting with empty data.")
        return {}
    except Exception as e:
        print(f"Error loading successful replies log from S3: {e}")
        return {}

def save_successful_replies_log_to_s3(data):
    """Save the log of successfully replied posts to S3."""
    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=SUCCESSFUL_REPLIES_LOG_KEY,
            Body=json.dumps(data, indent=2),
            ContentType='application/json'
        )
        print(f"Successfully saved successful replies log to s3://{BUCKET_NAME}/{SUCCESSFUL_REPLIES_LOG_KEY}")
    except Exception as e:
        print(f"Error saving successful replies log to S3: {e}")

def lambda_handler(event, context):
    """AWS Lambda handler function"""
    try:
        print("Starting Reddit bot lambda function...")
        
        # Load environment variables
        credentials = load_environment_variables()
        
        # Define subreddits to check - get from environment or use default
        subreddits_raw = os.environ.get('SUBREDDITS', 'testingground4bots')
        subreddits_to_check = [s.strip() for s in subreddits_raw.split(',')]
        print(f"Checking subreddits: {subreddits_to_check}")
        
        # Load previously processed posts log from S3
        processed_posts_log_data = load_processed_posts_log_from_s3()
        # Load previously successful replies log from S3
        successful_replies_log_data = load_successful_replies_log_from_s3()
        
        # Check and reply to posts, and get status of log update
        processed_posts_log_data, successful_replies_log_data, new_replies_made, log_updated = check_and_reply_to_posts(
            credentials, subreddits_to_check, processed_posts_log_data, successful_replies_log_data
        )
        
        # Save processed posts log to S3 if it was updated
        if log_updated:
            save_processed_posts_log_to_s3(processed_posts_log_data)
            print("Updated processed posts log in S3")
        else:
            print("No new posts processed or existing posts updated, no S3 log update needed")
        
        # Save successful replies log to S3 if new replies were made
        if new_replies_made:
            save_successful_replies_log_to_s3(successful_replies_log_data)
            print("Updated successful replies log in S3")
        else:
            print("No new successful replies, successful replies log not updated in S3")
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Reddit bot executed successfully",
                "subreddits_checked": subreddits_to_check,
                "new_replies": new_replies_made,
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