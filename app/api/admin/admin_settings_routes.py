# app/api/admin/admin_settings_routes.py

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.tenant import Tenant
from app.utils.security import encrypt_api_key, decrypt_api_key
from app.utils.email_service import send_test_email

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


@router.get("/admin/settings/email", response_class=HTMLResponse)
async def admin_email_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    """Display email settings configuration page"""
    result = await db.execute(
        select(Tenant).where(Tenant.id == user.tenant_id)
    )
    tenant = result.scalar_one_or_none()

    # Decrypt API key for display (show masked version)
    api_key_display = ""
    if tenant and tenant.resend_api_key_encrypted:
        decrypted_key = decrypt_api_key(tenant.resend_api_key_encrypted)
        if decrypted_key:
            # Show first 8 chars + masked remainder
            api_key_display = f"{decrypted_key[:8]}{'*' * (len(decrypted_key) - 8)}"

    return templates.TemplateResponse(
        "admin/email_settings.html",
        {
            "request": request,
            "user": user,
            "tenant": tenant,
            "api_key_display": api_key_display,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/admin/settings/email/update")
async def update_email_settings(
    request: Request,
    resend_api_key: str = Form(""),
    order_notification_email: str = Form(""),
    from_email: str = Form(""),
    enable_order_emails: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    """Update email notification settings"""
    result = await db.execute(
        select(Tenant).where(Tenant.id == user.tenant_id)
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        return RedirectResponse(
            url="/admin/settings/email?error=Tenant+not+found",
            status_code=303,
        )

    # Update settings
    tenant.order_notification_email = order_notification_email.strip()
    tenant.from_email = from_email.strip()
    tenant.enable_order_emails = enable_order_emails

    # Only update API key if a new one is provided
    if resend_api_key and resend_api_key.strip():
        encrypted_key = encrypt_api_key(resend_api_key.strip())
        tenant.resend_api_key_encrypted = encrypted_key

    await db.commit()

    return RedirectResponse(
        url="/admin/settings/email?success=Settings+saved+successfully",
        status_code=303,
    )


@router.post("/admin/settings/email/test")
async def test_email_configuration(
    request: Request,
    test_email: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    """Send a test email to verify RESEND configuration"""
    result = await db.execute(
        select(Tenant).where(Tenant.id == user.tenant_id)
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        return RedirectResponse(
            url="/admin/settings/email?error=Tenant+not+found",
            status_code=303,
        )

    # Send test email
    email_result = send_test_email(tenant, test_email.strip())

    if email_result["success"]:
        return RedirectResponse(
            url=f"/admin/settings/email?success=Test+email+sent+to+{test_email}",
            status_code=303,
        )
    else:
        error_msg = email_result.get("message", "Unknown error")
        return RedirectResponse(
            url=f"/admin/settings/email?error={error_msg.replace(' ', '+')}",
            status_code=303,
        )


@router.post("/admin/settings/email/clear")
async def clear_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    """Clear stored RESEND API key"""
    result = await db.execute(
        select(Tenant).where(Tenant.id == user.tenant_id)
    )
    tenant = result.scalar_one_or_none()

    if tenant:
        tenant.resend_api_key_encrypted = None
        tenant.enable_order_emails = False
        await db.commit()

    return RedirectResponse(
        url="/admin/settings/email?success=API+key+cleared",
        status_code=303,
    )
