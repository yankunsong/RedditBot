import praw
import os
import json
import time
import random
from datetime import datetime
import pytz
from openai import OpenAI
import praw.exceptions
import boto3

def load_environment_variables():
    """Load environment variables from Lambda environment"""
    # Assuming this runs in Lambda, environment variables are directly available
    return {
        "username": os.getenv("USERNAME"),
        "password": os.getenv("PASSWORD"),
        "client_id": os.getenv("CLIENT_ID"),
        "client_secret": os.getenv("CLIENT_SECRET"),
        "user_agent": os.getenv("USER_AGENT"),
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
        "post_scan_limit": int(os.getenv("POST_SCAN_LIMIT", 25)), # Default to 25 posts
        "SQS_QUEUE_URL": os.getenv("SQS_QUEUE_URL")
    }

def get_reddit_instance(credentials):
    """Initialize and return a Reddit instance"""
    return praw.Reddit(
        client_id=credentials["client_id"],
        client_secret=credentials["client_secret"],
        user_agent=credentials["user_agent"],
        username=credentials["username"],
        password=credentials["password"],
    )

def is_suitable_art_style_match(title, body, openai_client):
    """
    Use OpenAI to determine if a post is seeking an artist with a style similar to ours.
    The style is: light-hearted, healing, whimsical, humorous, and warm illustrations
    for children's content or other compatible projects.
    
    Ignores posts from artists seeking work (e.g., [FOR HIRE] posts).
    
    Returns a boolean and a confidence score.
    """
    # Check for common tags indicating artists looking for work
    lower_title = title.lower()
    if "[for hire]" in lower_title:
        print(f"Skipping artist-seeking-work post: {title}")
        return False, 0.0
    
    # Combine title and body for better context
    content = f"Title: {title}\n\nContent: {body}"
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """You are an assistant that determines if a Reddit post is seeking an artist with a specific style.

First, determine if the post is FROM an artist looking for work (which we should ignore) or FROM someone LOOKING TO HIRE an artist (which we want to respond to).

IGNORE posts where the person is an artist advertising their services or looking for clients.
ONLY consider posts where someone is looking to hire or commission an artist.

Your response MUST be a valid JSON object.

If the post is from an artist looking for work, respond with the following JSON structure: {"is_relevant": false, "confidence": 0.0, "is_artist_seeking_work": true}

If the post is from someone looking to hire an artist, then evaluate if they're looking for an artist with this style:
- Light-hearted, healing, whimsical, humorous, and warm
- Aims to convey warmth and happiness while positively influencing young minds
- Focuses on children's books and products, but is versatile across mediums
- Works with illustrations, paper sculptures, fabric mascots, stop-motion animation
- Strong emphasis on conceptual exploration
- Thoughtful use of color theory

Consider posts seeking artists for:
- Children's books or products
- Light-hearted, whimsical, or warm illustration styles
- Projects needing a positive, uplifting aesthetic
- Family-friendly or educational content
- Character design with warmth and personality

If the post is from someone looking to hire an artist matching our style, respond with the following JSON structure:
{"is_relevant": true, "confidence": 0.X, "is_artist_seeking_work": false}

If the post is from someone looking to hire an artist but NOT matching our style, respond with the following JSON structure:
{"is_relevant": false, "confidence": 0.X, "is_artist_seeking_work": false}

Where 0.X is your confidence level from 0.0 to 1.0. Ensure your output is only the JSON object."""},
                {"role": "user", "content": f"Is the following Reddit post seeking an artist with a style matching or compatible with the description above? The post doesn't have to be specifically about children's books - it could be any project where this style would be appropriate. Remember to first determine if the post is FROM an artist looking for work (ignore) or FROM someone LOOKING TO HIRE an artist (consider). Provide your response as a JSON object.\n\n{content}"}
            ],
            response_format={"type": "json_object"}
        )
        
        # Extract response
        result = json.loads(response.choices[0].message.content)
        is_relevant = result.get("is_relevant", False)
        confidence = result.get("confidence", 0.0)
        is_artist_seeking_work = result.get("is_artist_seeking_work", False)
        
        # Log the result for debugging
        if is_artist_seeking_work:
            print(f"Post is from an artist seeking work, ignoring: {title}")
            return False, 0.0
        
        print(f"AI analysis: relevant={is_relevant}, confidence={confidence:.2f}")
        print(f"Post title: {title}")
        
        # Only consider it relevant if the confidence is high enough
        if is_relevant and confidence >= 0.7:
            return True, confidence
        return False, confidence
        
    except Exception as e:
        print(f"Error in OpenAI API call: {e}")
        # Default to not relevant if there's an error
        return False, 0.0

def generate_customized_response(title, body, openai_client):
    """
    Generate a concise customized response (within 50 words) based on the post content
    and add the personal website at the end.
    """
    content = f"Title: {title}\n\nContent: {body}"
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """You are an illustrator with a light-hearted, whimsical, warm style who specializes in children's content but is versatile across different mediums.

Your art style is:
- Light-hearted, healing, whimsical, humorous, and warm
- Aims to convey warmth and happiness while positively influencing young minds
- Focuses on children's books and products, but is versatile across mediums
- Works with illustrations, paper sculptures, fabric mascots, stop-motion animation
- Strong emphasis on conceptual exploration
- Thoughtful use of color theory

Create a VERY BRIEF personalized reply to this Reddit post (maximum 50 words). Make it friendly and directly relevant to what they're looking for. Focus only on how your style matches their specific needs.

DO NOT include your website or contact information in this part - that will be added separately.
"""}, 
                {"role": "user", "content": f"Here's the Reddit post to respond to:\n\n{content}"}
            ],
            max_tokens=250
        )
        
        personalized_part = response.choices[0].message.content.strip()
        
        # Add the website information as a separate part
        website_part = f"\n\nYou can see my portfolio and contact me at: https://wenqinggu.com"
        
        # Combine the two parts
        complete_response = personalized_part + website_part
        
        print("Generated customized response")
        return complete_response
        
    except Exception as e:
        print(f"Error generating customized response: {e}")
        # Fall back to default response if there's an error
        default_intro = "Hi there! I think my whimsical, light-hearted style would be perfect for your project. I specialize in warm, engaging illustrations that resonate with viewers of all ages."
        return f"{default_intro}\n\nYou can see my portfolio at: https://wenqinggu.com"

def check_and_reply_to_posts(credentials, subreddits_to_check, processed_posts_log_data, successful_queued_messages_data):
    """Check posts, send relevant ones to SQS with delay, log all processing, and log successful queueing."""
    openai_client = OpenAI(api_key=credentials["openai_api_key"])
    post_scan_limit = credentials.get("post_scan_limit", 25)
    reddit_instance = get_reddit_instance(credentials)
    
    # Initialize SQS client
    sqs_client = None
    sqs_queue_url = credentials.get("SQS_QUEUE_URL") # Changed from SNS_TOPIC_ARN
    if sqs_queue_url:
        sqs_client = boto3.client('sqs') # Changed from 'sns'
    else:
        print("Warning: SQS_QUEUE_URL not set. Will not send to SQS.")

    new_messages_queued = False # Renamed from new_publications_made
    log_updated_this_run = False
    pacific_tz = pytz.timezone('US/Pacific')
    current_utc_timestamp = int(time.time())

    for subreddit_name in subreddits_to_check:
        print(f"Checking subreddit: r/{subreddit_name}")
        subreddit = reddit_instance.subreddit(subreddit_name)
        try:
            posts_iterable = subreddit.new(limit=post_scan_limit)
        except praw.exceptions.APIException as api_e:
            print(f"Failed to fetch posts from r/{subreddit_name} due to APIException:")
            print(f"  Error Type: {api_e.error_type}")
            print(f"  Message: {api_e.message}")
            if api_e.field:
                print(f"  Field: {api_e.field}")
            print(f"  Raw PRAW Exception: {api_e}")
            print(f"Skipping subreddit r/{subreddit_name} due to API error.")
            # Log this error in processed_posts_log_data if needed, perhaps under a special key
            # For now, just print and continue to the next subreddit
            continue # Skip to the next subreddit
        except Exception as e:
            print(f"Failed to fetch posts from r/{subreddit_name} due to a general error: {e}")
            print(f"  Error Type: {type(e).__name__}")
            print(f"Skipping subreddit r/{subreddit_name} due to error.")
            # Log this error similarly
            continue # Skip to the next subreddit

        for post in posts_iterable:
            if post.id in processed_posts_log_data:
                # Optionally, update a "last_seen" timestamp if desired
                # For now, just skip if already processed.
                print(f"Post {post.id} already processed. Skipping.")
                continue

            # New post, mark log for update and record initial processing attempt
            log_updated_this_run = True
            timestamp = current_utc_timestamp # Use consistent timestamp for this run
            utc_time = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
            pacific_time = utc_time.astimezone(pacific_tz)
            readable_time = pacific_time.strftime('%Y-%m-%d %H:%M:%S %Z')

            processed_posts_log_data[post.id] = {
                "first_processed_timestamp": timestamp,
                "first_processed_readable_time": readable_time,
                "title": post.title,
                "url": f"https://www.reddit.com{post.permalink}",
                "subreddit": subreddit_name,
                "analysis_status": "pending",
                "queue_status": "not_attempted" # Changed from publish_status
            }
            
            title = post.title
            selftext = post.selftext or ""
            
            is_relevant, confidence = is_suitable_art_style_match(title, selftext, openai_client)
            
            # Update log with analysis results
            processed_posts_log_data[post.id]["analysis_status"] = "relevant" if is_relevant else "irrelevant"
            processed_posts_log_data[post.id]["ai_confidence"] = confidence
            # We can infer "is_artist_seeking_work" based on confidence=0.0 if that specific output is desired
            # For now, is_suitable_art_style_match handles this internally by returning False, 0.0

            if is_relevant:
                processed_posts_log_data[post.id]["queue_status"] = "attempting" # Changed from publish_status
                try:
                    customized_response = generate_customized_response(title, selftext, openai_client)
                    
                    if sqs_client and sqs_queue_url:
                        message_to_send = {
                            "postId": post.id,
                            "postTitle": post.title,
                            "postUrl": f"https://www.reddit.com{post.permalink}",
                            "subreddit": subreddit_name,
                            "responseBody": customized_response,
                            "aiConfidence": confidence
                        }
                        delay_seconds = random.randint(60, 600) # Random delay between 1 and 10 minutes
                        
                        sqs_client.send_message(
                            QueueUrl=sqs_queue_url,
                            MessageBody=json.dumps(message_to_send),
                            DelaySeconds=delay_seconds
                        )
                        print(f"Successfully sent message for post: {post.id} - {post.title} to SQS with {delay_seconds}s delay.")
                        
                        processed_posts_log_data[post.id]["queue_status"] = "success" # Changed from publish_status
                        queue_timestamp = int(time.time())
                        processed_posts_log_data[post.id]["queue_timestamp"] = queue_timestamp
                        processed_posts_log_data[post.id]["queued_message_summary"] = customized_response[:100] + ("..." if len(customized_response) > 100 else "")
                        processed_posts_log_data[post.id]["queue_delay_seconds"] = delay_seconds
                        new_messages_queued = True # Renamed from new_publications_made

                        utc_queue_time = datetime.fromtimestamp(queue_timestamp, tz=pytz.UTC)
                        pacific_queue_time = utc_queue_time.astimezone(pacific_tz)
                        readable_queue_time = pacific_queue_time.strftime('%Y-%m-%d %H:%M:%S %Z')
                        successful_queued_messages_data[post.id] = { # Renamed variable
                            "timestamp": queue_timestamp,
                            "readable_time": readable_queue_time,
                            "title": post.title,
                            "url": processed_posts_log_data[post.id]["url"],
                            "subreddit": subreddit_name,
                            "ai_confidence": confidence,
                            "queued_message_summary": customized_response[:200] + ("..." if len(customized_response) > 200 else ""),
                            "delay_seconds": delay_seconds
                        }
                    else:
                        print(f"SQS client or Queue URL not available. Skipping SQS send for post: {post.id}")
                        processed_posts_log_data[post.id]["queue_status"] = "skipped_sqs_not_configured"

                except Exception as e:
                    print(f"Failed to send message for post {post.id} to SQS due to an error: {e}")
                    print(f"  Error Type: {type(e).__name__}")
                    processed_posts_log_data[post.id]["queue_status"] = "failure" # Changed from publish_status
                    processed_posts_log_data[post.id]["queue_error"] = str(e) # Changed from publish_error
                    processed_posts_log_data[post.id]["queue_error_type"] = type(e).__name__ # Changed from publish_error_type
            else:
                processed_posts_log_data[post.id]["queue_status"] = "not_applicable_irrelevant" # Changed from publish_status
                    
    return processed_posts_log_data, successful_queued_messages_data, new_messages_queued, log_updated_this_run 