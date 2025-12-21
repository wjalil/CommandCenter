import os
from dotenv import load_dotenv


load_dotenv()
# Debug: Print what's loaded
print("🔍 Checking environment variables:")
print(f"TWILIO_ACCOUNT_SID: {os.getenv('TWILIO_ACCOUNT_SID')}")
print(f"TWILIO_AUTH_TOKEN: {os.getenv('TWILIO_AUTH_TOKEN')}")
print(f"TWILIO_PHONE_NUMBER: {os.getenv('TWILIO_PHONE_NUMBER')}")
print(f"DISPATCHER_PHONE_NUMBER: {os.getenv('DISPATCHER_PHONE_NUMBER')}")
print()

from app.utils.twilio_client import send_order_alert, send_customer_ack
# Test dispatcher alert
send_order_alert(
    to_phone="+17187757343",  # Your dispatcher number
    customer_name="Test Customer",
    customer_phone="+17187757343",
    items=[{"name": "Burger", "qty": 2}, {"name": "Fries", "qty": 1}]
)

print("✅ Test alert sent!")

# Test customer confirmation
send_customer_ack(
    to_phone="+17187757343",  # Send to your own phone for testing
    customer_name="Test Customer"
)

print("✅ Test confirmation sent!")