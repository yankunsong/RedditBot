import praw
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Access the variables using os.getenv()
username = os.getenv("USERNAME")
password = os.getenv("PASSWORD")
client_id = os.getenv("CLIENT_ID")
client_secret = os.getenv("CLIENT_SECRET")
user_agent = os.getenv("USER_AGENT")


reddit_instance = praw.Reddit(
    client_id=client_id,
    client_secret=client_secret,
    user_agent=user_agent,
    username=username,
    password=password,
)

print(reddit_instance.user.me())
subreddit_cat = reddit_instance.subreddit("cats")
top_5_cat_posts = subreddit_cat.hot(limit=5)

for post in top_5_cat_posts:
    print(post.title)
    print(post.url)
    print(post.score)
    print(post.num_comments)
    print(post.author)
    print(post.created_utc)
    print("--------------------------------")