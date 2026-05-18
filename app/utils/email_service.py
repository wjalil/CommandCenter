# app/utils/email_service.py

from typing import Any
import os
import resend
from app.models.tenant import Tenant
from app.models.customer.customer import Customer
from app.utils.security import decrypt_api_key


def send_new_order_email(
    tenant: Tenant,
    customer: Customer,
    items_summary: list[dict[str, Any]],
    order_id: str,
    order_note: str = "",
    order_total: float = 0.00,
) -> dict[str, Any]:
    """
    Send email notification for new customer order using tenant's RESEND API key.

    Args:
        tenant: Tenant object with RESEND configuration
        customer: Customer who placed the order
        items_summary: List of dicts with 'name' and 'qty' keys
        order_id: Order ID for reference
        order_note: Optional customer note

    Returns:
        dict with 'success' (bool) and 'message' (str)
    """
    # Check if email notifications are enabled
    if not tenant.enable_order_emails:
        return {"success": False, "message": "Email notifications disabled for tenant"}

    # Validate required tenant configuration
    if not tenant.resend_api_key_encrypted:
        return {"success": False, "message": "RESEND API key not configured"}

    if not tenant.order_notification_email:
        return {"success": False, "message": "Order notification email not configured"}

    if not tenant.from_email:
        return {"success": False, "message": "From email not configured"}

    # Decrypt API key
    api_key = decrypt_api_key(tenant.resend_api_key_encrypted)
    if not api_key:
        return {"success": False, "message": "Failed to decrypt RESEND API key"}

    # Build HTML email content
    html_content = _build_order_email_html(
        customer_name=customer.name,
        customer_phone=customer.phone_number or "N/A",
        items_summary=items_summary,
        order_id=order_id,
        order_note=order_note,
        tenant_name=tenant.name,
        order_total=order_total,
    )

    # Send email via RESEND
    try:
        # Set API key (this is a global setting in resend library)
        resend.api_key = api_key

        # Validate email parameters
        if not customer.name:
            return {"success": False, "message": "Customer name is missing"}

        params = {
            "from": tenant.from_email,
            "to": [tenant.order_notification_email],
            "subject": f"New Order from {customer.name}",
            "html": html_content,
        }

        # Log params for debugging (without sensitive data)
        print(f"📧 Sending order email:")
        print(f"  From: {params['from']}")
        print(f"  To: {params['to']}")
        print(f"  Subject: {params['subject']}")
        print(f"  API Key Length: {len(api_key)}")
        print(f"  API Key Prefix: {api_key[:10] if len(api_key) >= 10 else api_key[:4]}...")

        email_result = resend.Emails.send(params)

        return {
            "success": True,
            "message": f"Email sent successfully (ID: {email_result.get('id', 'unknown')})",
            "email_id": email_result.get('id'),
        }

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Email send error: {error_msg}")
        print(f"  Exception type: {type(e).__name__}")
        return {"success": False, "message": f"Failed to send email: {error_msg}"}


def _build_order_email_html(
    customer_name: str,
    customer_phone: str,
    items_summary: list[dict[str, Any]],
    order_id: str,
    order_note: str,
    tenant_name: str,
    order_total: float = 0.00,
) -> str:
    """Build HTML email template for new order notification"""

    # Build items table rows
    items_rows = ""
    for item in items_summary:
        price = item.get('price', 0.00)
        qty = item.get('qty', 0)
        line_total = item.get('total', price * qty)

        items_rows += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">{item['name']}</td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; text-align: center;">×{qty}</td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; text-align: right;">${price:.2f}</td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; text-align: right; font-weight: 600;">${line_total:.2f}</td>
            </tr>
        """

    # Customer note section (only if provided)
    note_section = ""
    if order_note:
        note_section = f"""
            <div style="background-color: #fef3c7; padding: 16px; border-radius: 8px; margin-top: 20px; border-left: 4px solid #f59e0b;">
                <p style="margin: 0; font-weight: 600; color: #92400e; margin-bottom: 8px;">Customer Note:</p>
                <p style="margin: 0; color: #78350f;">{order_note}</p>
            </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>New Order Notification</title>
    </head>
    <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f3f4f6;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff;">
            <!-- Header -->
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 32px; text-align: center;">
                <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 700;">New Order Received!</h1>
                <p style="margin: 8px 0 0 0; color: #e0e7ff; font-size: 14px;">Order #{order_id[:8]}</p>
            </div>

            <!-- Content -->
            <div style="padding: 32px;">
                <!-- Customer Info -->
                <div style="background-color: #f9fafb; padding: 20px; border-radius: 8px; margin-bottom: 24px;">
                    <h2 style="margin: 0 0 16px 0; font-size: 18px; color: #111827;">Customer Information</h2>
                    <div style="display: flex; flex-direction: column; gap: 8px;">
                        <div style="display: flex; align-items: center;">
                            <span style="font-weight: 600; color: #6b7280; width: 100px;">Name:</span>
                            <span style="color: #111827;">{customer_name}</span>
                        </div>
                        <div style="display: flex; align-items: center;">
                            <span style="font-weight: 600; color: #6b7280; width: 100px;">Phone:</span>
                            <span style="color: #111827;">{customer_phone}</span>
                        </div>
                    </div>
                </div>

                <!-- Order Items -->
                <div style="margin-bottom: 24px;">
                    <h2 style="margin: 0 0 16px 0; font-size: 18px; color: #111827;">Order Items</h2>
                    <table style="width: 100%; border-collapse: collapse; background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden;">
                        <thead>
                            <tr style="background-color: #f9fafb;">
                                <th style="padding: 12px; text-align: left; font-weight: 600; color: #6b7280; border-bottom: 2px solid #e5e7eb;">Item</th>
                                <th style="padding: 12px; text-align: center; font-weight: 600; color: #6b7280; border-bottom: 2px solid #e5e7eb;">Qty</th>
                                <th style="padding: 12px; text-align: right; font-weight: 600; color: #6b7280; border-bottom: 2px solid #e5e7eb;">Price</th>
                                <th style="padding: 12px; text-align: right; font-weight: 600; color: #6b7280; border-bottom: 2px solid #e5e7eb;">Total</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items_rows}
                        </tbody>
                        <tfoot>
                            <tr style="background-color: #f9fafb;">
                                <td colspan="3" style="padding: 16px; text-align: right; font-weight: 700; font-size: 16px; color: #111827; border-top: 2px solid #e5e7eb;">Order Total:</td>
                                <td style="padding: 16px; text-align: right; font-weight: 700; font-size: 18px; color: #667eea; border-top: 2px solid #e5e7eb;">${order_total:.2f}</td>
                            </tr>
                        </tfoot>
                    </table>
                </div>

                {note_section}

                <!-- Action Button -->
                <div style="text-align: center; margin-top: 32px;">
                    <a href="#" style="display: inline-block; background-color: #667eea; color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: 600; font-size: 16px;">View Order in Dashboard</a>
                </div>
            </div>

            <!-- Footer -->
            <div style="background-color: #f9fafb; padding: 24px; text-align: center; border-top: 1px solid #e5e7eb;">
                <p style="margin: 0; color: #6b7280; font-size: 14px;">{tenant_name}</p>
                <p style="margin: 8px 0 0 0; color: #9ca3af; font-size: 12px;">This email was sent automatically when a new order was placed.</p>
            </div>
        </div>
    </body>
    </html>
    """

    return html


def send_test_email(tenant: Tenant, test_recipient: str) -> dict[str, Any]:
    """
    Send a test email to verify RESEND configuration.

    Args:
        tenant: Tenant object with RESEND configuration
        test_recipient: Email address to send test to

    Returns:
        dict with 'success' (bool) and 'message' (str)
    """
    if not tenant.resend_api_key_encrypted or not tenant.from_email:
        return {"success": False, "message": "RESEND not fully configured"}

    api_key = decrypt_api_key(tenant.resend_api_key_encrypted)
    if not api_key:
        return {"success": False, "message": "Failed to decrypt API key"}

    try:
        # Set API key (this is a global setting in resend library)
        resend.api_key = api_key

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="font-family: sans-serif; padding: 40px; background-color: #f3f4f6;">
            <div style="max-width: 500px; margin: 0 auto; background: white; padding: 32px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                <h1 style="color: #667eea; margin-top: 0;">RESEND Test Email</h1>
                <p style="color: #374151; line-height: 1.6;">
                    This is a test email from <strong>{tenant.name}</strong>.
                    Your RESEND integration is working correctly!
                </p>
                <div style="background-color: #f0fdf4; padding: 16px; border-radius: 6px; margin-top: 24px; border-left: 4px solid #10b981;">
                    <p style="margin: 0; color: #065f46; font-weight: 600;">Configuration Verified</p>
                    <p style="margin: 8px 0 0 0; color: #047857; font-size: 14px;">Email notifications are ready to use.</p>
                </div>
            </div>
        </body>
        </html>
        """

        params = {
            "from": tenant.from_email,
            "to": [test_recipient],
            "subject": f"Test Email from {tenant.name} - RESEND Configuration",
            "html": html_content,
        }

        # Log params for debugging (without sensitive data)
        print(f"📧 Sending test email:")
        print(f"  From: {params['from']}")
        print(f"  To: {params['to']}")
        print(f"  API Key Length: {len(api_key)}")
        print(f"  API Key Prefix: {api_key[:10] if len(api_key) >= 10 else api_key[:4]}...")

        email_result = resend.Emails.send(params)

        return {
            "success": True,
            "message": f"Test email sent successfully (ID: {email_result.get('id', 'unknown')})",
        }

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Test email error: {error_msg}")
        print(f"  Exception type: {type(e).__name__}")
        return {"success": False, "message": f"Test email failed: {error_msg}"}


def send_tracking_email(tenant: Tenant, job: Any, tracking_url: str) -> dict[str, Any]:
    """
    Send a repair tracking link to the customer.
    Uses the tenant's Resend config if available, otherwise falls back to the
    system RESEND_API_KEY env var. Returns {"success": bool, "message": str}.
    """
    if not job.customer_email:
        return {"success": False, "message": "No customer email on file"}

    # Resolve API key: prefer tenant config, fall back to system env var
    api_key: str | None = None
    from_email: str = "noreply@cookieops.app"

    if tenant and tenant.resend_api_key_encrypted and tenant.from_email:
        api_key = decrypt_api_key(tenant.resend_api_key_encrypted)
        from_email = tenant.from_email

    if not api_key:
        api_key = os.getenv("RESEND_API_KEY")

    if not api_key:
        return {"success": False, "message": "Email not configured — add RESEND_API_KEY to .env"}

    shop_name = tenant.name if tenant else "Your Repair Shop"
    vehicle = " ".join(filter(None, [job.vehicle_year, job.vehicle_make, job.vehicle_model])) or "your vehicle"
    ticket = job.ticket_number or ""

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
    <body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f1f5f9;">
      <div style="max-width:560px;margin:40px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">
        <div style="background:#0f172a;padding:28px 32px;">
          <p style="margin:0;font-size:11px;font-weight:700;color:#14b8a6;letter-spacing:.08em;text-transform:uppercase;">{shop_name}</p>
          <h1 style="margin:8px 0 0;font-size:22px;font-weight:700;color:#fff;letter-spacing:-.02em;">Track Your Repair</h1>
        </div>
        <div style="padding:32px;">
          <p style="margin:0 0 8px;font-size:14px;color:#64748b;">Hi {job.customer_name},</p>
          <p style="margin:0 0 24px;font-size:15px;color:#0f172a;line-height:1.6;">
            You can check the live status of your <strong>{vehicle}</strong> (Ticket&nbsp;{ticket}) anytime using the link below.
          </p>
          <div style="text-align:center;margin:0 0 28px;">
            <a href="{tracking_url}"
               style="display:inline-block;background:#14b8a6;color:#fff;text-decoration:none;padding:14px 32px;border-radius:8px;font-size:15px;font-weight:600;letter-spacing:-.01em;">
              View Repair Status
            </a>
          </div>
          <p style="margin:0;font-size:12px;color:#94a3b8;text-align:center;">
            Or paste this link in your browser:<br>
            <span style="color:#14b8a6;">{tracking_url}</span>
          </p>
        </div>
        <div style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:16px 32px;text-align:center;">
          <p style="margin:0;font-size:12px;color:#94a3b8;">{shop_name} · sent automatically</p>
        </div>
      </div>
    </body>
    </html>
    """

    try:
        resend.api_key = api_key
        result = resend.Emails.send({
            "from": from_email,
            "to": [job.customer_email],
            "subject": f"Track your {vehicle} repair — {ticket}",
            "html": html,
        })
        return {"success": True, "message": f"Sent to {job.customer_email} (ID: {result.get('id', '?')})"}
    except Exception as e:
        print(f"❌ Tracking email error: {e}")
        return {"success": False, "message": str(e)}
