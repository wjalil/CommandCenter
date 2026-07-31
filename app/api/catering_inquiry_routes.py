# app/api/catering_inquiry_routes.py
"""Public, unauthenticated endpoint for the marketing website's catering
inquiry forms (index.html, preschool-catering.html, events.html on
chaiandbiscuitcatering.com). Sends a plain notification email via the
tenant's existing Resend configuration -- separate from order notifications,
so it does not touch tenant.order_notification_email.
"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr
from sqlalchemy.future import select
import resend

from app.db import async_session
from app.models.tenant import Tenant
from app.utils.security import decrypt_api_key

router = APIRouter()

CATERING_INQUIRY_RECIPIENT = "chaiandbiscuitcatering@gmail.com"
CATERING_TENANT_NAME = "Chai and Biscuit"


class CateringInquiry(BaseModel):
    name: str
    email: EmailStr
    message: str = ""
    organization: str = ""
    phone: str = ""
    program_type: str = ""
    ages_served: str = ""
    enrollment_size: str = ""
    diet_halal: str = ""
    diet_kosher: str = ""
    diet_vegetarian: str = ""
    diet_allergies: str = ""
    source_page: str = ""


def _build_inquiry_html(payload: CateringInquiry) -> str:
    fields = [
        ("Organization", payload.organization),
        ("Contact Name", payload.name),
        ("Email", payload.email),
        ("Phone", payload.phone),
        ("Program Type", payload.program_type),
        ("Ages Served", payload.ages_served),
        ("Children Enrolled", payload.enrollment_size),
        ("Halal", payload.diet_halal),
        ("Kosher", payload.diet_kosher),
        ("Vegetarian/Vegan", payload.diet_vegetarian),
        ("Food Allergies", payload.diet_allergies),
        ("Source Page", payload.source_page),
    ]
    rows = "".join(
        f"<tr><td style='padding:4px 12px;font-weight:600;color:#1a2941;'>{label}</td>"
        f"<td style='padding:4px 12px;'>{value}</td></tr>"
        for label, value in fields
        if value
    )
    return f"""
        <div style="font-family: Arial, sans-serif;">
            <h2 style="color:#1a2941;">New Catering Inquiry</h2>
            <table style="border-collapse: collapse;">{rows}</table>
            <p style="margin-top:16px;"><strong>Message:</strong><br>{payload.message}</p>
        </div>
    """


@router.post("/public/catering-inquiry")
async def submit_catering_inquiry(payload: CateringInquiry):
    async with async_session() as db:
        result = await db.execute(select(Tenant).where(Tenant.name == CATERING_TENANT_NAME))
        tenant: Optional[Tenant] = result.scalar_one_or_none()

    if not tenant or not tenant.resend_api_key_encrypted or not tenant.from_email:
        return {"success": False, "message": "Email is not configured for this business yet."}

    api_key = decrypt_api_key(tenant.resend_api_key_encrypted)
    if not api_key:
        return {"success": False, "message": "Failed to decrypt email API key."}

    try:
        resend.api_key = api_key
        result = resend.Emails.send({
            "from": tenant.from_email,
            "to": [CATERING_INQUIRY_RECIPIENT],
            "reply_to": payload.email,
            "subject": f"Catering Inquiry from {payload.name}",
            "html": _build_inquiry_html(payload),
        })
        return {"success": True, "message": "Inquiry sent", "email_id": result.get("id")}
    except Exception as e:
        return {"success": False, "message": f"Failed to send email: {e}"}
