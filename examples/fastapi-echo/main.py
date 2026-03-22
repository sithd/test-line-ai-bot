# -*- coding: utf-8 -*-

#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       https://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import os
import sys

from fastapi import Request, FastAPI, HTTPException
from anthropic import AsyncAnthropic

from linebot.v3.webhook import WebhookParser
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)


# get channel_secret and channel_access_token from your environment variable
channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)
if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)

configuration = Configuration(
    access_token=channel_access_token
)

app = FastAPI()
#async_api_client = AsyncApiClient(configuration)
#line_bot_api = AsyncMessagingApi(async_api_client)
parser = WebhookParser(channel_secret)

# Load Anthropic key 
# Remember to add this to Vercel env vars
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
if ANTHROPIC_API_KEY is None:
    print('Specify ANTHROPIC_API_KEY as environment variable.')
    sys.exit(1)

@app.post("/callback")
async def handle_callback(request: Request):
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = await request.body()
    body = body.decode()

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
        
# Create async client HERE — inside the async handler
    async with AsyncApiClient(configuration) as async_api_client:
        line_bot_api = AsyncMessagingApi(async_api_client)

        for event in events:
            if not isinstance(event, MessageEvent):
                continue
            if not isinstance(event.message, TextMessageContent):
                continue

            # Your test prefix
            #reply_text = "Auto Echo Test: " + event.message.text
            user_message = event.message.text
            
            
            # Call Claude
            try:
                client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

                response = await client.messages.create(
                    model="claude-sonnet-4-20250514",          
                    max_tokens=400,                            
                    temperature=0.7,
                    system=(
                        "You are a friendly and helpful customer support "
                        "and sales assistant. Be concise, polite, accurate, "
                        "and upbeat. Answer questions about products, "
                        "services, hours, or orders. If unsure, say "
                        "'Let me check that for you' or suggest contacting support."
                    ),
                    messages=[
                        {"role": "user", "content": user_message}
                    ]
                )

                reply_text = response.content[0].text.strip()

            except Exception as e:
                print(f"Claude error: {str(e)}")
                reply_text = "Sorry, I'm having trouble thinking right now. Please try again later!"

            await line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )

    return 'OK'