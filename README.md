You can get your developer credentials from https://www.reddit.com/prefs/apps

# Reddit Bot for Children's Book Illustrators

This bot scans Reddit for posts seeking artists with a light-hearted, whimsical style and automatically replies to them.

## AWS Lambda Deployment

### Prerequisites

- AWS account with appropriate permissions
- AWS CLI installed and configured
- S3 bucket for storing the bot's state (this will include `processed_posts_log.json` and `successful_replies_log.json`)

### Setup Instructions

1. **Create an S3 Bucket**

   Create an S3 bucket to store the replied posts data:

   ```
   aws s3 mb s3://your-reddit-bot-bucket-name
   ```

2. **Package the Lambda Function**

   Install dependencies and create a deployment package:

   ```
   pip install -r requirements.txt -t ./package
   cp *.py ./package/
   cd package
   zip -r ../deployment-package.zip .
   cd ..
   ```

3. **Create the Lambda Function**

   ```
   aws lambda create-function \
     --function-name RedditBot-Panda \
     --zip-file fileb://deployment-package.zip \
     --handler main.lambda_handler \
     --runtime python3.12 \
     --timeout 500 \
     --memory-size 128 \
     --role arn:aws:iam::409365783261:role/service-role/lambda_s3_iam_role
   ```

4. **Set Environment Variables**

   Configure the Lambda environment variables in the AWS Console or with AWS CLI:

   ```
   aws lambda update-function-configuration \
     --function-name RedditBot-Panda \
     --environment "Variables={USERNAME=your_reddit_username,PASSWORD=your_reddit_password,CLIENT_ID=your_client_id,CLIENT_SECRET=your_client_secret,USER_AGENT=your_user_agent,OPENAI_API_KEY=your_openai_api_key,S3_BUCKET_NAME=your-reddit-bot-bucket-name,SUBREDDITS='forhire,hireanartist,artcommissions,hungryartists'}"
   ```

5. **Create a CloudWatch Event Rule**

   Set up a scheduled trigger to run your bot periodically:

   ```
   aws events put-rule \
     --name RedditBotSchedule \
     --schedule-expression "rate(1 hour)"
   ```

   Then connect it to your Lambda function:

   ```
   aws lambda add-permission \
     --function-name RedditBot \
     --statement-id cwe-invoke \
     --action lambda:InvokeFunction \
     --principal events.amazonaws.com \
     --source-arn arn:aws:events:region:your-account-id:rule/RedditBotSchedule
   ```

   ```
   aws events put-targets \
     --rule RedditBotSchedule \
     --targets "Id"="1","Arn"="arn:aws:lambda:region:your-account-id:function:RedditBot"
   ```

6. **IAM Role Permissions**

   Ensure the Lambda execution role has permissions to:

   - Read/write to the S3 bucket
   - Write to CloudWatch Logs
   - Invoke OpenAI API (outbound HTTPS)

## Local Testing

To test the bot locally before deploying to Lambda:

1. Create a `.env` file with your credentials:

   ```
   USERNAME=your_reddit_username
   PASSWORD=your_reddit_password
   CLIENT_ID=your_client_id
   CLIENT_SECRET=your_client_secret
   USER_AGENT=your_user_agent
   OPENAI_API_KEY=your_openai_api_key
   ```

2. Run the script directly:
   ```
   python reddit_bot.py
   ```
   This will use/create `processed_posts_log.json` and `successful_replies_log.json` in your local project directory.

## Customization

- Edit the `illustration_response` in `reddit_bot.py` with your personal introduction and portfolio details
- Adjust the subreddits to monitor in the `SUBREDDITS` environment variable
- Modify the confidence threshold in the `is_suitable_art_style_match` function
