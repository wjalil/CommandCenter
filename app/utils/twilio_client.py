import os
from typing import Optional, List

from twilio.rest import Client

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_PHONE_NUMBER")

def _get_client() -> Optional[Client]:
    if not TWILIO_SID or not TWILIO_AUTH:
        return None
    return Client(TWILIO_SID, TWILIO_AUTH)

def send_sms(to_phone: str, body: str) -> None:
    """
    Fire-and-forget SMS. Never raises.
    """
    try:
        if not to_phone:
            return
        if not TWILIO_FROM:
            print("❌ TWILIO_PHONE_NUMBER missing")
            return
        client = _get_client()
        if not client:
            print("❌ Twilio credentials missing (SID/AUTH)")
            return

        client.messages.create(
            body=body,
            from_=TWILIO_FROM,
            to=to_phone
        )
    except Exception as e:
        print(f"❌ SMS failed: {e}")

def send_order_alert(to_phone: str, customer_name: str, customer_phone: str, items: List[dict]) -> None:
    item_list = ", ".join([f"{i['name']} x{i['qty']}" for i in items])
    message = f"🆕 New order from {customer_name} ({customer_phone}): {item_list}"
    send_sms(to_phone=to_phone, body=message)

def send_customer_ack(to_phone: str, customer_name: str) -> None:
    message = f"Hi {customer_name} — we received your order. We’ll be in touch shortly."
    send_sms(to_phone=to_phone, body=message)
