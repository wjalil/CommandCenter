# utils/twilio_client.py
from twilio.rest import Client
import os

# Ideally load from environment variables
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_PHONE_NUMBER")

client = Client(TWILIO_SID, TWILIO_AUTH)

def send_order_alert(to_phone: str, customer_name: str, customer_phone: str, items: list):
    item_list = ", ".join([f"{i['name']} x{i['qty']}" for i in items])
    message = f"🆕 New order from {customer_name} ({customer_phone}): {item_list}"

    client.messages.create(
        body=message,
        from_=TWILIO_FROM,
        to=to_phone
    )
