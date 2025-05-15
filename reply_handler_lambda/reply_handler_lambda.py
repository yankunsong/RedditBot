import json
import os
import praw
import praw.exceptions

# It's good practice to initialize clients outside the handler for reuse
reddit_instance = None

def load_lambda_environment_variables():
    """Load environment variables for the reply handler Lambda."""
    # Environment variables are directly available in Lambda
    return {
        "username": os.getenv("REDDIT_USERNAME"), # Using specific names to avoid conflict if deployed together
        "password": os.getenv("REDDIT_PASSWORD"),
        "client_id": os.getenv("REDDIT_CLIENT_ID"),
        "client_secret": os.getenv("REDDIT_CLIENT_SECRET"),
        "user_agent": os.getenv("REDDIT_USER_AGENT"),
    }

def get_reddit_instance_lazy(credentials):
    """Initialize and return a Reddit instance, reusing if already initialized."""
    global reddit_instance
    if reddit_instance is None:
        print("Initializing PRAW Reddit instance...")
        try:
            reddit_instance = praw.Reddit(
                client_id=credentials["client_id"],
                client_secret=credentials["client_secret"],
                user_agent=credentials["user_agent"],
                username=credentials["username"],
                password=credentials["password"],
                # check_for_async=False # Add if running in an async environment and PRAW complains
            )
            # Validate credentials by trying to fetch a simple object, e.g., me()
            # This helps to catch auth issues early.
            if reddit_instance.user.me():
                 print(f"Successfully authenticated to Reddit as {reddit_instance.user.me().name}")
            else:
                # This case should ideally not happen if praw.Reddit() succeeds without exceptions
                # and me() returns a user. But as a safeguard:
                print("Reddit authentication appeared successful but could not fetch user. Check credentials.")
                # Potentially raise an error here or handle as critical failure.
                # For now, it will likely fail later when trying to reply.
        except praw.exceptions.PrawcoreException as e:
            print(f"PRAW Core Exception during Reddit initialization: {e}")
            # This could be due to config issues, invalid credentials, etc.
            # reddit_instance will remain None, and subsequent operations will fail.
            raise  # Re-raise the exception to signal a critical failure.
        except Exception as e:
            print(f"Generic exception during Reddit initialization: {e}")
            raise # Re-raise
    return reddit_instance

def lambda_handler(event, context):
    """
    AWS Lambda handler for processing messages directly from SQS to reply to Reddit posts.
    """
    print(f"Reply Handler Lambda invoked. Event: {json.dumps(event)}")
    
    credentials = load_lambda_environment_variables()
    if not all([credentials.get(k) for k in ["username", "password", "client_id", "client_secret", "user_agent"]]):
        print("Error: Missing Reddit credentials in environment variables for Reply Handler Lambda.")
        # Depending on SQS retry policy, this might retry.
        # Consider returning an error or raising an exception to prevent reprocessing if credentials are truly missing.
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Missing Reddit credentials'})
        }

    try:
        reddit = get_reddit_instance_lazy(credentials)
        if not reddit: # Should not happen if get_reddit_instance_lazy raises on failure
            print("Error: Failed to initialize Reddit instance. Cannot proceed.")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Reddit initialization failed'})
            }
    except Exception as e:
        print(f"Critical error during Reddit instance initialization: {e}")
        # This will cause the Lambda to fail and SQS to retry (if configured)
        # or send to DLQ.
        raise

    successful_replies = 0
    failed_replies = 0

    for record in event.get('Records', []):
        try:
            print(f"Processing SQS record: {record.get('messageId')}")
            
            # The message from SQS comes directly in record['body']
            # This 'body' is a stringified JSON of our message payload
            message_body_str = record.get('body')
            if not message_body_str:
                print(f"Skipping record {record.get('messageId')} due to empty body.")
                failed_replies += 1
                continue
            
            message_data = json.loads(message_body_str) # Directly parse the SQS message body
            
            post_id = message_data.get('postId')
            response_body = message_data.get('responseBody')
            post_title = message_data.get('postTitle', 'N/A') # For logging

            if not post_id or not response_body:
                print(f"Missing postId or responseBody in message for record {record.get('messageId')}. Data: {message_data}")
                failed_replies += 1
                continue

            print(f"Attempting to reply to post ID: {post_id}, Title: {post_title}")
            
            try:
                submission = reddit.submission(id=post_id)
                submission.reply(response_body)
                print(f"Successfully replied to post ID: {post_id}, Title: {post_title}")
                successful_replies += 1
            except praw.exceptions.APIException as api_e:
                # This handles Reddit API errors like rate limits, forbidden actions, etc.
                print(f"PRAW APIException replying to post {post_id} (Title: {post_title}): {api_e}")
                print(f"  Error Type: {api_e.error_type}, Message: {api_e.message}, Field: {api_e.field}")
                failed_replies += 1
            except praw.exceptions.PrawcoreException as pcore_e:
                # Handles lower-level PRAW issues (e.g., network problems, auth already handled)
                print(f"PRAW Core Exception replying to post {post_id} (Title: {post_title}): {pcore_e}")
                failed_replies += 1
            except Exception as e:
                print(f"Generic unexpected error replying to post {post_id} (Title: {post_title}): {e}")
                failed_replies += 1
        
        except json.JSONDecodeError as json_e:
            print(f"Failed to decode JSON for SQS record {record.get('messageId')}: {json_e}")
            print(f"Problematic record body: {record.get('body')}")
            failed_replies += 1
        except Exception as e:
            # Catch-all for errors during the processing of a single record
            print(f"Unexpected error processing SQS record {record.get('messageId')}: {e}")
            failed_replies += 1

    print(f"Lambda execution finished. Successful replies: {successful_replies}, Failed replies: {failed_replies}")
    
    # The Lambda will return 200 OK if it processed the batch, even if some individual messages failed.
    # SQS will remove successfully processed messages from the queue.
    # Failures in message processing are logged and SQS redrive policy / DLQ should handle persistent errors.
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Reply handler processed SQS event.',
            'successful_replies': successful_replies,
            'failed_replies': failed_replies
        })
    }

# Removed the if __name__ == "__main__": block as it was for local testing. 