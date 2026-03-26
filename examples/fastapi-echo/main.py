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

# Load product information from text file
PRODUCT_INFO = ""

try:
    with open("products.txt", "r", encoding="utf-8") as f:
        PRODUCT_INFO = f.read().strip()
    print(f"Loaded product information: {len(PRODUCT_INFO)} characters")
except FileNotFoundError:
    print("Warning: products.txt not found. Place it in the same folder as main.py")
    PRODUCT_INFO = "No product information available."
except Exception as e:
    print(f"Error loading products.txt: {e}")
    PRODUCT_INFO = "No product information available."

app = FastAPI()

# In-memory conversation history: user_id → list of {"role": ..., "content": ...}
conversation_history = {}

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

            user_id = event.source.user_id
            user_message = event.message.text

            # Initialize history for this user if it doesn't exist
            if user_id not in conversation_history:
                conversation_history[user_id] = []

            # Add user's message to history
            conversation_history[user_id].append({"role": "user", "content": user_message})

            # Limit history to last 10 messages to control cost
            if len(conversation_history[user_id]) > 10:
                conversation_history[user_id] = conversation_history[user_id][-10:]

            print(f"User {user_id[:8]}... | History length: {len(conversation_history[user_id])}")

            try:
                client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

                response = await client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=400,
                    temperature=0.7,
                    system=(
                        "You are a professional customer support and sales assistant for my eyewear business in Bangkok, Thailand. "
                        "Your ONLY job is to help customers with questions about our products, services, business hours, "
                        "orders, pricing, shipping, returns, or promotions. "
                        
                        "Here is our current product and business information:\n"
                        f"{PRODUCT_INFO}\n\n"
                        
                        "Rules you MUST follow:"
                        "- If the user's message is about our business, products, or services → answer helpfully and accurately."
                        "- If the user's message is off-topic (e.g. asking for a story, joke, poem, personal advice, "
                        "  unrelated opinions, or anything not related to our business), respond politely with: "
                        "'Sorry, I'm here to help with only questions about our products and services. How can I assist you today?' "
                        "  and do not engage with the off-topic request."
                        "- Never write stories, poems, jokes, code, or creative content unless it directly relates to a product."
                        "- Stay professional, friendly, and concise."
                        "- If you're unsure about something business-related, say 'Let me check that for you' instead of guessing."
                    ),
                    messages=conversation_history[user_id]
                )

                reply_text = response.content[0].text.strip()

                # ── IMPORTANT: Add Claude's reply to history ─────────────
                conversation_history[user_id].append({"role": "assistant", "content": reply_text})

            except Exception as e:
                print(f"Claude error: {str(e)}")
                reply_text = "Sorry, I'm having trouble thinking right now. Please try again later!"

            # Send reply to LINE
            await line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )

    return 'OK'