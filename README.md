You can get your developer credentials from https://www.reddit.com/prefs/apps

# Reddit Bot for Artist Outreach

This bot scans specified subreddits for posts from users seeking artists with a particular style (light-hearted, whimsical, warm, suitable for children's content). When a relevant post is found, the bot generates a customized response and queues it to be posted as a reply after a random delay. This delay helps avoid potential Reddit API rate limiting or appearing too bot-like.

## Architecture Overview

The bot is comprised of two AWS Lambda functions and an AWS SQS queue:

1.  **Post Detector Lambda (`post_detector_lambda/`)**:

    - Triggered on a schedule (e.g., every 30 minutes) by a CloudWatch Event.
    - Scans configured subreddits for new posts.
    - Uses the OpenAI API to determine if a post is relevant and if the poster is looking to hire (not an artist advertising services).
    - If relevant, it generates a customized response.
    - Sends a message containing the post ID and the response body to an SQS queue with a random delay (1-10 minutes).
    - Logs processed posts and successfully queued messages to an S3 bucket.

2.  **SQS Queue**:

    - A standard SQS queue that receives messages from the Post Detector Lambda.
    - Utilizes SQS's per-message delay feature.

3.  **Reply Handler Lambda (`reply_handler_lambda/`)**:
    - Triggered when a message becomes visible in the SQS queue.
    - Parses the message to get the Reddit post ID and the response body.
    - Uses the PRAW library to post the response as a reply to the target Reddit post.

## Prerequisites

- AWS Account
- AWS CLI installed and configured locally (for initial setup if not using Infrastructure as Code)
- Git and a GitHub account (for deploying via GitHub Actions)

## AWS Resources Needed

- **Two AWS Lambda Functions**:
  - Post Detector Lambda
  - Reply Handler Lambda
- **Amazon S3 Bucket**: For the Post Detector Lambda to store logs of processed posts and queued messages.
- **Amazon SQS Standard Queue**: To decouple the post detection from the reply action and to introduce delays.
- **IAM Roles**:
  - An execution role for the Post Detector Lambda with permissions for:
    - CloudWatch Logs (write)
    - S3 (read/write to the designated bucket)
    - SQS (send messages to the designated queue)
    - Outbound internet access (for Reddit and OpenAI APIs)
  - An execution role for the Reply Handler Lambda with permissions for:
    - CloudWatch Logs (write)
    - SQS (read/delete messages from the designated queue)
    - Outbound internet access (for Reddit API)
- **CloudWatch Event Rule (Scheduler)**: To trigger the Post Detector Lambda periodically.

## Environment Variables

These must be configured in the AWS Lambda environment settings for each function.

**For `Post Detector Lambda`:**

- `USERNAME`: Your Reddit bot account username.
- `PASSWORD`: Your Reddit bot account password.
- `CLIENT_ID`: Your Reddit app's client ID.
- `CLIENT_SECRET`: Your Reddit app's client secret.
- `USER_AGENT`: Your Reddit app's user agent string (e.g., `MyRedditBot/1.0 by u/your_username`).
- `OPENAI_API_KEY`: Your OpenAI API key.
- `S3_BUCKET_NAME`: The name of the S3 bucket for logs.
- `SQS_QUEUE_URL`: The URL of the SQS queue.
- `SUBREDDITS`: A comma-separated list of subreddits to scan (e.g., `forhire,artcommissions,hungryartists`).
- `POST_SCAN_LIMIT` (Optional): Number of posts to scan per subreddit run (defaults to 25).

**For `Reply Handler Lambda`:**

- `REDDIT_USERNAME`: Your Reddit bot account username.
- `REDDIT_PASSWORD`: Your Reddit bot account password.
- `REDDIT_CLIENT_ID`: Your Reddit app's client ID.
- `REDDIT_CLIENT_SECRET`: Your Reddit app's client secret.
- `REDDIT_USER_AGENT`: Your Reddit app's user agent string.

_(Note: The `.env` files present in the Lambda directories are primarily for aiding local development or direct invocation if necessary, but for deployed Lambdas, the above AWS environment variables are used.)_

## Deployment via GitHub Actions

Deployment of both Lambda functions is automated via the GitHub Actions workflow defined in `.github/workflows/deploy-lambda.yml`.

- **Trigger**: The workflow runs automatically on pushes to the `main` or `develop` branches.
- **Process**:

  1.  Checks out the code.
  2.  Configures AWS credentials using OIDC (role specified in the workflow).
  3.  For each Lambda function defined in its matrix (`PostDetector` and `ReplyHandler`):
      - Builds a deployment package (installs dependencies from its specific `requirements.txt`, copies Python files).
      - Creates a `.zip` file for the Lambda.
  4.  Deploys each `.zip` file to the corresponding AWS Lambda function.

- **IMPORTANT**: Before the first deployment, or if you change your Lambda function names in AWS, you **MUST** update the `aws_name` placeholders (`YourPostDetectorLambdaName`, `YourReplyHandlerLambdaName`) in the `.github/workflows/deploy-lambda.yml` file to match your actual AWS Lambda function names.

## AWS Setup Steps (High-Level)

While the GitHub Actions workflow handles code deployment, the initial AWS resources need to be created:

1.  **Create S3 Bucket**: For logging by the Post Detector Lambda.
2.  **Create SQS Standard Queue**: For messages. Note its URL.
3.  **Create IAM Roles**: One for each Lambda with the permissions listed under "AWS Resources Needed."
4.  **Create Lambda Functions**:
    - **Post Detector Lambda**:
      - Runtime: Python 3.12
      - Handler: `post_detector_lambda.main.lambda_handler`
      - Assign its IAM role.
      - Configure its environment variables.
      - Set timeout & memory as needed (e.g., 500 seconds, 256MB).
    - **Reply Handler Lambda**:
      - Runtime: Python 3.12
      - Handler: `reply_handler_lambda.reply_handler_lambda.lambda_handler`
      - Assign its IAM role.
      - Configure its environment variables.
      - Set timeout & memory as needed (e.g., 180 seconds, 128MB).
5.  **Configure Triggers**:
    - **Post Detector**: Create a CloudWatch Event Rule (e.g., `rate(30 minutes)`) and set the Post Detector Lambda as its target.
    - **Reply Handler**: Configure the SQS queue as the trigger for the Reply Handler Lambda. Set an appropriate batch size (e.g., 1, if you want to process replies one by one and ensure the delay is honored per reply).

## Local Testing (Limited)

While the system is designed for AWS, limited local testing was part of the development:

- **Post Detector Lambda**:
  - You can potentially run `python post_detector_lambda/reddit_bot.py` for testing the core post scanning and OpenAI logic.
  - To do this, you would need a `.env` file inside the `post_detector_lambda` directory with the necessary credentials (`USERNAME`, `PASSWORD`, `CLIENT_ID`, `CLIENT_SECRET`, `USER_AGENT`, `OPENAI_API_KEY`).
  - If `SQS_QUEUE_URL` and S3 bucket details are in the `.env` (or environment), it would attempt real AWS interactions.
- **Reply Handler Lambda**:
  - This Lambda is designed to be triggered by SQS. Direct local testing is less straightforward without mocking SQS events. Its `.env` file would contain Reddit credentials.

_For robust testing, deploying to a development environment in AWS is recommended._

## Customization

- **OpenAI Prompts & Logic**: Modify the prompts and logic within `is_suitable_art_style_match` and `generate_customized_response` functions in `post_detector_lambda/reddit_bot.py` to change how the bot identifies relevant posts and crafts replies.
- **Target Subreddits**: Adjust the `SUBREDDITS` environment variable for the Post Detector Lambda.
- **Reply Delay**: The delay is a random number of seconds between 60 and 600 (1 to 10 minutes), configured in `post_detector_lambda/reddit_bot.py` within the `check_and_reply_to_posts` function.
- **Scan Limit**: The `POST_SCAN_LIMIT` environment variable for the Post Detector Lambda controls how many recent posts are checked in each subreddit per run.
