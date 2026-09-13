"""
Catering client portal: login, dashboard, read-only menu/invoice viewing,
and item requests (condiments, spoons, count changes, etc.) for
CateringClientAccount users.
"""
import json
from calendar import monthcalendar, month_name, setfirstweekday, SUNDAY
from datetime import date as dt_date, datetime as dt

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db import get_db
from app.auth.dependencies import get_current_catering_client
from app.models.catering.client_account import CateringClientAccount
from app.models.tenant import Tenant
from app.crud.catering import (
    client_account as client_account_crud,
    portal_request as portal_request_crud,
    program as program_crud,
    monthly_menu as menu_crud,
    invoice as invoice_crud,
    cacfp_rules,
)
from app.api.catering.html_routes import _build_component_preview, _generate_invoice_pdf_bytes
from app.utils.email_service import send_portal_invite_email, send_portal_password_reset_email

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def _get_tenant_by_slug(slug: str, db: AsyncSession):
    result = await db.execute(select(Tenant).where(Tenant.slug == slug.lower()))
    return result.scalar_one_or_none()


# ==================== PUBLIC (slug-scoped) AUTH ====================

@router.get("/t/{slug}/portal/login", response_class=HTMLResponse)
async def portal_login_get(request: Request, slug: str, db: AsyncSession = Depends(get_db)):
    tenant = await _get_tenant_by_slug(slug, db)
    if not tenant:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("catering/portal_login.html", {"request": request, "tenant": tenant})


@router.post("/t/{slug}/portal/login", response_class=HTMLResponse)
async def portal_login_post(
    request: Request,
    slug: str,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _get_tenant_by_slug(slug, db)
    if not tenant:
        return RedirectResponse("/", status_code=302)

    account = await client_account_crud.authenticate(db, tenant.id, email, password)
    if account:
        request.session["user_id"] = account.id
        request.session["role"] = "catering_client"
        request.session["tenant_id"] = tenant.id
        return RedirectResponse(url="/portal/", status_code=302)

    return templates.TemplateResponse(
        "catering/portal_login.html",
        {
            "request": request,
            "tenant": tenant,
            "error": "Invalid email or password.",
            "prefill_email": email.strip(),
        },
    )


@router.get("/t/{slug}/portal/forgot-password", response_class=HTMLResponse)
async def portal_forgot_password_get(request: Request, slug: str, db: AsyncSession = Depends(get_db)):
    tenant = await _get_tenant_by_slug(slug, db)
    if not tenant:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("catering/portal_forgot_password.html", {"request": request, "tenant": tenant})


@router.post("/t/{slug}/portal/forgot-password", response_class=HTMLResponse)
async def portal_forgot_password_post(
    request: Request,
    slug: str,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _get_tenant_by_slug(slug, db)
    if not tenant:
        return RedirectResponse("/", status_code=302)

    account = await client_account_crud.start_password_reset(db, tenant.id, email)
    if account:
        reset_url = str(request.base_url).rstrip("/") + f"/t/{slug}/portal/reset-password/{account.reset_token}"
        send_portal_password_reset_email(tenant, account.email, reset_url)

    # Always show the same confirmation, whether or not the email matched an account
    return templates.TemplateResponse(
        "catering/portal_forgot_password.html",
        {"request": request, "tenant": tenant, "submitted": True},
    )


@router.get("/t/{slug}/portal/reset-password/{token}", response_class=HTMLResponse)
async def portal_reset_password_get(request: Request, slug: str, token: str, db: AsyncSession = Depends(get_db)):
    tenant = await _get_tenant_by_slug(slug, db)
    if not tenant:
        return RedirectResponse("/", status_code=302)

    account = await client_account_crud.get_by_reset_token(db, token)
    if not account or account.tenant_id != tenant.id:
        return templates.TemplateResponse(
            "catering/portal_reset_password.html",
            {"request": request, "tenant": tenant, "token": token, "invalid": True},
        )

    return templates.TemplateResponse(
        "catering/portal_reset_password.html",
        {"request": request, "tenant": tenant, "token": token, "invalid": False},
    )


@router.post("/t/{slug}/portal/reset-password/{token}", response_class=HTMLResponse)
async def portal_reset_password_post(
    request: Request,
    slug: str,
    token: str,
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _get_tenant_by_slug(slug, db)
    if not tenant:
        return RedirectResponse("/", status_code=302)

    account = await client_account_crud.get_by_reset_token(db, token)
    if not account or account.tenant_id != tenant.id:
        return templates.TemplateResponse(
            "catering/portal_reset_password.html",
            {"request": request, "tenant": tenant, "token": token, "invalid": True},
        )

    if len(password) < 8 or password != confirm_password:
        return templates.TemplateResponse(
            "catering/portal_reset_password.html",
            {
                "request": request,
                "tenant": tenant,
                "token": token,
                "invalid": False,
                "error": "Passwords must match and be at least 8 characters.",
            },
        )

    await client_account_crud.complete_password_reset(db, account, password)
    return RedirectResponse(url=f"/t/{slug}/portal/login", status_code=302)


# ==================== PUBLIC (slug-scoped) INVITE ACCEPTANCE ====================

@router.get("/t/{slug}/portal/invite/{token}", response_class=HTMLResponse)
async def portal_invite_get(request: Request, slug: str, token: str, db: AsyncSession = Depends(get_db)):
    tenant = await _get_tenant_by_slug(slug, db)
    if not tenant:
        return RedirectResponse("/", status_code=302)

    account = await client_account_crud.get_by_invite_token(db, token)
    if not account or account.tenant_id != tenant.id:
        return templates.TemplateResponse(
            "catering/portal_invite_accept.html",
            {"request": request, "tenant": tenant, "token": token, "invalid": True},
        )

    return templates.TemplateResponse(
        "catering/portal_invite_accept.html",
        {
            "request": request,
            "tenant": tenant,
            "token": token,
            "invalid": False,
            "program_name": account.program.name,
            "email": account.email,
        },
    )


@router.post("/t/{slug}/portal/invite/{token}", response_class=HTMLResponse)
async def portal_invite_post(
    request: Request,
    slug: str,
    token: str,
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _get_tenant_by_slug(slug, db)
    if not tenant:
        return RedirectResponse("/", status_code=302)

    account = await client_account_crud.get_by_invite_token(db, token)
    if not account or account.tenant_id != tenant.id:
        return templates.TemplateResponse(
            "catering/portal_invite_accept.html",
            {"request": request, "tenant": tenant, "token": token, "invalid": True},
        )

    if len(password) < 8 or password != confirm_password:
        return templates.TemplateResponse(
            "catering/portal_invite_accept.html",
            {
                "request": request,
                "tenant": tenant,
                "token": token,
                "invalid": False,
                "program_name": account.program.name,
                "email": account.email,
                "error": "Passwords must match and be at least 8 characters.",
            },
        )

    account = await client_account_crud.accept_invite(db, account, password)
    request.session["user_id"] = account.id
    request.session["role"] = "catering_client"
    request.session["tenant_id"] = tenant.id
    return RedirectResponse(url="/portal/", status_code=302)


# ==================== AUTHENTICATED PORTAL ====================

@router.get("/portal/login", response_class=HTMLResponse)
async def portal_login_placeholder(request: Request):
    return RedirectResponse("/?error=Please+enter+your+workspace+name+to+sign+in", status_code=302)


@router.get("/portal/", response_class=HTMLResponse)
async def portal_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    account: CateringClientAccount = Depends(get_current_catering_client),
):
    program = account.program
    menus = await menu_crud.get_monthly_menus(db, account.tenant_id, program.id)
    visible_menus = [m for m in menus if m.status != "draft"]
    latest_menu = visible_menus[0] if visible_menus else None

    invoices = await invoice_crud.get_invoices(db, account.tenant_id, program.id)
    recent_invoices = invoices[:5]

    open_requests = [
        r for r in await portal_request_crud.get_requests_for_program(db, program.id, account.tenant_id)
        if r.status != "resolved"
    ]

    return templates.TemplateResponse(
        "catering/portal_dashboard.html",
        {
            "request": request,
            "account": account,
            "program": program,
            "latest_menu": latest_menu,
            "recent_invoices": recent_invoices,
            "open_requests_count": len(open_requests),
        },
    )


# -------------------- Menus --------------------

@router.get("/portal/menus", response_class=HTMLResponse)
async def portal_menus_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    account: CateringClientAccount = Depends(get_current_catering_client),
):
    menus = await menu_crud.get_monthly_menus(db, account.tenant_id, account.program_id)
    visible_menus = [m for m in menus if m.status != "draft"]
    return templates.TemplateResponse(
        "catering/portal_menus_list.html",
        {"request": request, "account": account, "program": account.program, "menus": visible_menus},
    )


@router.get("/portal/menus/{menu_id}", response_class=HTMLResponse)
async def portal_menu_view(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    account: CateringClientAccount = Depends(get_current_catering_client),
):
    monthly_menu = await menu_crud.get_monthly_menu(db, menu_id, account.tenant_id)
    if not monthly_menu or monthly_menu.program_id != account.program_id or monthly_menu.status == "draft":
        return RedirectResponse(url="/portal/menus", status_code=303)

    program = await program_crud.get_program(db, monthly_menu.program_id, account.tenant_id)

    service_days = json.loads(program.service_days) if isinstance(program.service_days, str) else (program.service_days or [])
    meal_types = json.loads(program.meal_types_required) if isinstance(program.meal_types_required, str) else (program.meal_types_required or [])

    setfirstweekday(SUNDAY)
    month_weeks = monthcalendar(monthly_menu.year, monthly_menu.month)

    menu_days_dict = {day.service_date.isoformat(): day for day in monthly_menu.menu_days}
    holiday_dates = {h.holiday_date.isoformat() for h in program.holidays} if program.holidays else set()

    fruit_portions = await cacfp_rules.get_fruit_portions(db, program.age_group_id) if program.cacfp_eligible else {}

    calendar_weeks = []
    for week in month_weeks:
        week_data = []
        for day_num in week:
            if day_num == 0:
                week_data.append({
                    'day': '', 'date': '', 'in_month': False, 'is_service_day': False,
                    'is_holiday': False, 'menu_day': None,
                    'component_preview': {'breakfast': '', 'lunch': '', 'snack': '', 'am_snack': '', 'pm_snack': ''}
                })
            else:
                date_obj = dt_date(monthly_menu.year, monthly_menu.month, day_num)
                date_str = date_obj.isoformat()
                day_name = date_obj.strftime('%A')
                is_service_day = day_name in service_days
                menu_day = menu_days_dict.get(date_str)

                week_data.append({
                    'day': day_num,
                    'date': date_str,
                    'in_month': True,
                    'is_service_day': is_service_day,
                    'is_holiday': date_str in holiday_dates,
                    'menu_day': menu_day,
                    'component_preview': _build_component_preview(menu_day, fruit_portions)
                })
        calendar_weeks.append(week_data)

    show_sunday = 'Sunday' in service_days
    show_saturday = 'Saturday' in service_days

    return templates.TemplateResponse("catering/menu_share.html", {
        "request": request,
        "monthly_menu": monthly_menu,
        "program": program,
        "month_name": month_name[monthly_menu.month],
        "year": monthly_menu.year,
        "service_days": service_days,
        "meal_types": meal_types,
        "calendar_weeks": calendar_weeks,
        "generated_date": dt.now().strftime('%B %d, %Y'),
        "show_sunday": show_sunday,
        "show_saturday": show_saturday,
        "portal_view": True,
    })


@router.get("/portal/menus/{menu_id}/pdf")
async def portal_menu_pdf(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    account: CateringClientAccount = Depends(get_current_catering_client),
):
    monthly_menu = await menu_crud.get_monthly_menu(db, menu_id, account.tenant_id)
    if not monthly_menu or monthly_menu.program_id != account.program_id or monthly_menu.status == "draft":
        return RedirectResponse(url="/portal/menus", status_code=303)

    program = account.program
    service_days = json.loads(program.service_days) if isinstance(program.service_days, str) else (program.service_days or [])
    meal_types = json.loads(program.meal_types_required) if isinstance(program.meal_types_required, str) else (program.meal_types_required or [])

    setfirstweekday(SUNDAY)
    month_weeks = monthcalendar(monthly_menu.year, monthly_menu.month)
    menu_days_dict = {day.service_date.isoformat(): day for day in monthly_menu.menu_days}
    holiday_dates = {h.holiday_date.isoformat() for h in program.holidays} if program.holidays else set()
    fruit_portions = await cacfp_rules.get_fruit_portions(db, program.age_group_id) if program.cacfp_eligible else {}

    calendar_weeks = []
    for week in month_weeks:
        week_data = []
        for day_num in week:
            if day_num == 0:
                week_data.append({
                    'day': '', 'date': '', 'in_month': False, 'is_service_day': False,
                    'is_holiday': False, 'menu_day': None,
                    'component_preview': {'breakfast': '', 'lunch': '', 'snack': '', 'am_snack': '', 'pm_snack': ''}
                })
            else:
                date_obj = dt_date(monthly_menu.year, monthly_menu.month, day_num)
                date_str = date_obj.isoformat()
                is_service_day = date_obj.strftime('%A') in service_days
                menu_day = menu_days_dict.get(date_str)
                week_data.append({
                    'day': day_num,
                    'date': date_str,
                    'in_month': True,
                    'is_service_day': is_service_day,
                    'is_holiday': date_str in holiday_dates,
                    'menu_day': menu_day,
                    'component_preview': _build_component_preview(menu_day, fruit_portions)
                })
        calendar_weeks.append(week_data)

    show_sunday = 'Sunday' in service_days
    show_saturday = 'Saturday' in service_days

    html_content = templates.TemplateResponse("catering/menu_share.html", {
        "request": request,
        "monthly_menu": monthly_menu,
        "program": program,
        "month_name": month_name[monthly_menu.month],
        "year": monthly_menu.year,
        "service_days": service_days,
        "meal_types": meal_types,
        "calendar_weeks": calendar_weeks,
        "generated_date": dt.now().strftime('%B %d, %Y'),
        "show_sunday": show_sunday,
        "show_saturday": show_saturday,
        "portal_view": True,
    }).body.decode('utf-8')

    try:
        from xhtml2pdf import pisa
        import io as _io
        pdf_buffer = _io.BytesIO()
        pisa_status = pisa.CreatePDF(html_content, dest=pdf_buffer)
        if pisa_status.err:
            raise Exception(f"PDF generation failed with {pisa_status.err} errors")
        filename = f"{program.name.replace(' ', '_')}_{month_name[monthly_menu.month]}_{monthly_menu.year}_Menu.pdf"
        return Response(
            content=pdf_buffer.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception:
        return RedirectResponse(url=f"/portal/menus/{menu_id}?error=PDF+generation+failed", status_code=303)


# -------------------- Invoices --------------------

@router.get("/portal/invoices", response_class=HTMLResponse)
async def portal_invoices_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    account: CateringClientAccount = Depends(get_current_catering_client),
):
    invoices = await invoice_crud.get_invoices(db, account.tenant_id, account.program_id)
    return templates.TemplateResponse(
        "catering/portal_invoices_list.html",
        {"request": request, "account": account, "program": account.program, "invoices": invoices},
    )


@router.get("/portal/invoices/{invoice_id}/view", response_class=HTMLResponse)
async def portal_invoice_view(
    request: Request,
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    account: CateringClientAccount = Depends(get_current_catering_client),
):
    invoice = await invoice_crud.get_invoice(db, invoice_id, account.tenant_id)
    if not invoice or invoice.program_id != account.program_id:
        return RedirectResponse(url="/portal/invoices", status_code=303)

    return templates.TemplateResponse(
        "catering/portal_invoice_view.html",
        {"request": request, "account": account, "invoice": invoice},
    )


@router.get("/portal/invoices/{invoice_id}/pdf")
async def portal_invoice_pdf(
    request: Request,
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    account: CateringClientAccount = Depends(get_current_catering_client),
):
    invoice = await invoice_crud.get_invoice(db, invoice_id, account.tenant_id)
    if not invoice or invoice.program_id != account.program_id:
        return RedirectResponse(url="/portal/invoices", status_code=303)

    try:
        pdf_bytes = await _generate_invoice_pdf_bytes(request, db, invoice)
        date_str = invoice.service_date.strftime('%Y-%m-%d')
        filename = f"Invoice_{invoice.invoice_number}_{date_str}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception:
        return RedirectResponse(url=f"/portal/invoices/{invoice_id}/view?error=PDF+generation+failed", status_code=303)


# -------------------- Requests --------------------

@router.get("/portal/requests", response_class=HTMLResponse)
async def portal_requests_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    account: CateringClientAccount = Depends(get_current_catering_client),
):
    requests_list = await portal_request_crud.get_requests_for_program(db, account.program_id, account.tenant_id)
    return templates.TemplateResponse(
        "catering/portal_requests.html",
        {"request": request, "account": account, "program": account.program, "requests": requests_list},
    )


@router.post("/portal/requests", response_class=HTMLResponse)
async def portal_requests_create(
    request: Request,
    request_type: str = Form("general"),
    message: str = Form(...),
    db: AsyncSession = Depends(get_db),
    account: CateringClientAccount = Depends(get_current_catering_client),
):
    if request_type not in ("count_change", "menu_feedback", "general"):
        request_type = "general"

    await portal_request_crud.create_request(
        db,
        program_id=account.program_id,
        tenant_id=account.tenant_id,
        client_account_id=account.id,
        request_type=request_type,
        message=message.strip(),
    )
    return RedirectResponse(url="/portal/requests", status_code=303)
