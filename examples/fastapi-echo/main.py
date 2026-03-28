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
import smtplib
import datetime
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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


# ENV Variables
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

# Email configuration for escalations
EMAIL_SENDER = os.getenv('EMAIL_SENDER')          # Your Gmail address
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')      # Gmail App Password (NOT your regular password)
EMAIL_RECEIVER = os.getenv('EMAIL_RECEIVER')      # Your email to receive notifications

if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
    print("Warning: Email credentials not set. Escalation emails will not be sent.")

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
    
client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

def send_escalation_email(user_id: str, latest_message: str, history: list):
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        print(f"Email credentials missing. Skipping escalation for user {user_id[:8]}...")
        return

    try:
        subject = f"🚨 LINE Bot Escalation - User {user_id[:8]}..."

        # Build the email body properly
        body = f"""
                A customer has requested human assistance through the LINE bot.

                User ID: {user_id}
                Latest Message: {latest_message}

                Full Conversation History:
                """

        # Add conversation history with better formatting
        for i, msg in enumerate(history[-15:], 1):   # Show last 15 messages
            role = "👤 CUSTOMER" if msg["role"] == "user" else "🤖 BOT"
            body += f"\n{i}. {role}:\n{msg['content']}\n"

        body += "\n--- End of Conversation ---\n"
        body += f"Time: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        # Create email message
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECEIVER
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        # Send email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)

        print(f"✅ Escalation email sent successfully for user {user_id[:8]}...")

    except Exception as e:
        print(f"❌ Failed to send escalation email: {str(e)}")

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

            #print(f"User {user_id[:8]}... | History length: {len(conversation_history[user_id])}")

            try:
                #client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

                response = await client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=800,
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
                        "- Answer using customer's language or one that they prefer. (e.g. if the customer asked in German, respond in German."
                        "- You do not have the ability to search online. Do not offer to look on the web for availability or store directions."
                        "- Do not offer virtual try ons. The store doesn't have a working website."
                        "- If you're unsure about something business-related, say 'Let me check that for you' instead of guessing."
                        "- When a customer asks 'What are your products?', 'What do you sell?', or similar broad questions, "
                        "give a **short, friendly summary** first (2-4 sentences max). Do NOT list everything.\n"
                        "- After the summary, offer to provide more details. Example: "
                        "'We carry designer frames like Ray-Ban and Oakley, everyday fashion frames, sunglasses, "
                        "and a full range of lens options. Would you like recommendations based on your face shape, "
                        "or are you looking for something specific like blue light glasses or polarized sunglasses?'\n"
                        "- Only give detailed information when the customer asks for a specific category, brand, or product.\n"
                        "- Be concise, polite, and helpful. Try to guide the conversation naturally.\n"
                        "- Never send extremely long messages unless the customer specifically requests full details."
                        
                        "Refund and Return Policy Handling:"
                        "- Clearly explain our return policy: [insert your actual policy here, e.g. 30 days, must be unworn, original packaging, etc.]"
                        "- For any refund or return request, collect these details: order number, reason, date of purchase."
                        "- Be empathetic and professional."
                        "- Never approve or deny refunds yourself."
                        "- Always say something like: 'I'll forward this to our support team for review."
                        "- Escalate all refund requests to a human agent."
                        
                        "Escalation Rules:\n"
                        "- If the customer asks for a refund, return, damaged item, or has a serious complaint → respond with '[ESCALATE_TO_HUMAN]' at the very beginning of your response.\n"
                        "- If you are unsure how to handle the request or it involves money/policy decisions → respond with '[ESCALATE_TO_HUMAN]' at the beginning.\n"
                        "- For normal questions, respond normally without the tag.\n"
                        "- Always be polite and empathetic."
                    ),
                    messages=conversation_history[user_id]
                )

                raw_reply = response.content[0].text.strip()

                # Check for escalation tag
                if raw_reply.startswith("[ESCALATE_TO_HUMAN]"):
                    reply_text = "I understand this is important. I'll ping a human support team member right away. Please hold on for a moment."
                    #await send_escalation_email(user_id, user_message, conversation_history[user_id])
                    asyncio.create_task(
                        asyncio.to_thread(
                            send_escalation_email,
                            user_id,
                            user_message,
                            conversation_history[user_id]
                        )
                    )
                else:
                    reply_text = raw_reply

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