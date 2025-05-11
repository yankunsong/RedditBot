import praw
import os
import json
import time
import random
from datetime import datetime
import pytz
from openai import OpenAI
from dotenv import load_dotenv

def load_environment_variables():
    """Load environment variables from .env file or Lambda environment"""
    # In Lambda, we'll use environment variables directly
    # When testing locally, we'll use dotenv
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME") is None:
        load_dotenv()
    
    return {
        "username": os.getenv("USERNAME"),
        "password": os.getenv("PASSWORD"),
        "client_id": os.getenv("CLIENT_ID"),
        "client_secret": os.getenv("CLIENT_SECRET"),
        "user_agent": os.getenv("USER_AGENT"),
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
        "post_scan_limit": int(os.getenv("POST_SCAN_LIMIT", 25)) # Default to 25 posts
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

def load_processed_posts_log(log_file):
    """Load previously processed posts log from a JSON file"""
    if os.path.exists(log_file) and os.path.getsize(log_file) > 0:
        try:
            with open(log_file, "r") as f:
                log_data = json.load(f)
        except json.JSONDecodeError:
            print(f"Error reading {log_file}. Starting with empty data.")
            log_data = {}
    else:
        log_data = {}
    return log_data

def save_processed_posts_log(log_data, log_file, log_updated_this_run):
    """Save processed posts log to a JSON file if it was updated"""
    if log_updated_this_run:
        with open(log_file, "w") as f:
            json.dump(log_data, f, indent=2)
        print(f"Updated {log_file} with new post processing data")
    else:
        print("No new posts processed or existing posts updated in this execution (local file).")

# New functions for the successful replies log
SUCCESSFUL_REPLIES_LOG_FILENAME = "successful_replies_log.json"

def load_successful_replies_log(filename=SUCCESSFUL_REPLIES_LOG_FILENAME):
    """Load the log of successfully replied posts from a JSON file."""
    if os.path.exists(filename) and os.path.getsize(filename) > 0:
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Error reading {filename}. Starting with an empty log.")
            return {}
    return {}

def save_successful_replies_log(data, new_replies_were_made, filename=SUCCESSFUL_REPLIES_LOG_FILENAME):
    """Save the log of successfully replied posts to a JSON file if new replies were made."""
    if new_replies_were_made:
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Updated {filename} with new successful reply data.")
    else:
        print(f"No new successful replies in this execution, {filename} not updated.")

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

def check_and_reply_to_posts(credentials, subreddits_to_check, processed_posts_log_data, successful_replies_log_data):
    """Check posts, reply to relevant ones, log all processing, and log successful replies separately."""
    openai_client = OpenAI(api_key=credentials["openai_api_key"])
    post_scan_limit = credentials.get("post_scan_limit", 25)
    reddit_instance = get_reddit_instance(credentials)
    
    new_replies_made = False
    log_updated_this_run = False # For processed_posts_log
    pacific_tz = pytz.timezone('US/Pacific')
    current_utc_timestamp = int(time.time())

    for subreddit_name in subreddits_to_check:
        print(f"Checking subreddit: r/{subreddit_name}")
        subreddit = reddit_instance.subreddit(subreddit_name)
        for post in subreddit.new(limit=post_scan_limit):
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
                "analysis_status": "pending", # To be updated after OpenAI call
                "reply_status": "not_attempted"
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
                processed_posts_log_data[post.id]["reply_status"] = "attempting"
                try:
                    sleep_time = random.uniform(0, 15)
                    print(f"Waiting for {sleep_time:.2f} seconds before replying...")
                    time.sleep(sleep_time)
                    
                    customized_response = generate_customized_response(title, selftext, openai_client)
                    
                    post.reply(customized_response)
                    print(f"Replied to post: {post.id} - {post.title} (confidence: {confidence:.2f})")
                    
                    # Update processed posts log for success
                    processed_posts_log_data[post.id]["reply_status"] = "success"
                    reply_timestamp = int(time.time()) # Specific timestamp for reply
                    processed_posts_log_data[post.id]["reply_timestamp"] = reply_timestamp
                    processed_posts_log_data[post.id]["replied_with_response"] = customized_response[:200] + ("..." if len(customized_response) > 200 else "")
                    new_replies_made = True

                    # Add to successful replies log
                    utc_reply_time = datetime.fromtimestamp(reply_timestamp, tz=pytz.UTC)
                    pacific_reply_time = utc_reply_time.astimezone(pacific_tz)
                    readable_reply_time = pacific_reply_time.strftime('%Y-%m-%d %H:%M:%S %Z')
                    successful_replies_log_data[post.id] = {
                        "timestamp": reply_timestamp,
                        "readable_time": readable_reply_time,
                        "title": post.title,
                        "url": processed_posts_log_data[post.id]["url"],
                        "subreddit": subreddit_name,
                        "ai_confidence": confidence,
                        "response": customized_response
                    }
                    
                except Exception as e:
                    print(f"Failed to reply to post {post.id}: {e}")
                    processed_posts_log_data[post.id]["reply_status"] = "failure"
                    processed_posts_log_data[post.id]["reply_error"] = str(e)
            else:
                processed_posts_log_data[post.id]["reply_status"] = "not_applicable_irrelevant"
                    
    return processed_posts_log_data, successful_replies_log_data, new_replies_made, log_updated_this_run

def run_reddit_bot():
    """Main function to run the Reddit bot"""
    credentials = load_environment_variables()
    # subreddits_to_check = ["forhire", "hireanartist", "artcommissions", "hungryartists", "starvingartists", "commissions", "publishing", "writing", "selfpublish", "childrensbookillustration"]
    subreddits_to_check = ["testingground4bots"]
    
    processed_log_file = "processed_posts_log.json" 
    processed_posts_log_data = load_processed_posts_log(processed_log_file)
    
    # Load the successful replies log
    successful_replies_data = load_successful_replies_log()
    
    processed_posts_log_data, successful_replies_data, new_replies_made, log_updated_this_run = check_and_reply_to_posts(
        credentials, subreddits_to_check, processed_posts_log_data, successful_replies_data
    ) 
    
    save_processed_posts_log(processed_posts_log_data, processed_log_file, log_updated_this_run)
    # Save the successful replies log
    save_successful_replies_log(successful_replies_data, new_replies_made)
    
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Reddit bot executed successfully (local)",
            "new_replies": new_replies_made,
            "log_updated": log_updated_this_run
        })
    }

# This allows running directly for local testing
if __name__ == "__main__":
    run_reddit_bot()