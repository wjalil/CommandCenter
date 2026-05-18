"""
Auto Shop Admin Routes

Manage repair orders: create, update, status changes, photo uploads.
"""
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from typing import Optional
from datetime import datetime, date, timedelta
from collections import defaultdict
import uuid
import os
import shutil

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.user import User
from app.models.auto_shop.repair_order_payment import RepairOrderPayment, PAYMENT_METHOD_LABELS
from app.models.auto_shop import (
    RepairOrder,
    RepairOrderPhoto,
    RepairOrderStatusLog,
    RepairOrderPayment,
    VALID_STATUSES,
    STATUS_LABELS,
    STATUS_BADGE_COLORS,
    STATUS_SMS_MESSAGES,
    PAYMENT_TYPES,
    PAYMENT_TYPE_LABELS,
    PAYMENT_METHODS,
    PAYMENT_METHOD_LABELS,
)
from app.core.constants import UPLOAD_PATHS
from app.utils.twilio_client import send_sms

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PHOTO_DIR = UPLOAD_PATHS["auto_shop_photos"]


# ── helpers ──────────────────────────────────────────────────────────────────

async def _generate_ticket_number(db: AsyncSession, tenant_id: int) -> str:
    result = await db.execute(
        select(func.count(RepairOrder.id)).where(RepairOrder.tenant_id == tenant_id)
    )
    count = result.scalar() or 0
    return f"RO-{count + 1:04d}"


def _send_status_sms(order: RepairOrder, new_status: str) -> bool:
    template = STATUS_SMS_MESSAGES.get(new_status)
    if not template or not order.customer_phone:
        return False
    message = template.format(
        year=order.vehicle_year or "",
        make=order.vehicle_make or "vehicle",
        model=order.vehicle_model or "",
    ).strip()
    send_sms(to_phone=order.customer_phone, body=message)
    return True


def _template_ctx(request: Request, **kwargs) -> dict:
    return {
        "request": request,
        "status_labels": STATUS_LABELS,
        "status_badge_colors": STATUS_BADGE_COLORS,
        "valid_statuses": VALID_STATUSES,
        "payment_types": PAYMENT_TYPES,
        "payment_type_labels": PAYMENT_TYPE_LABELS,
        "payment_methods": PAYMENT_METHODS,
        "payment_method_labels": PAYMENT_METHOD_LABELS,
        **kwargs,
    }


# ── dashboard ─────────────────────────────────────────────────────────────────

ACTIVE_STATUSES = [s for s in VALID_STATUSES if s not in ("complete", "ready_for_pickup")]

@router.get("/")
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id
    today = date.today()

    # All open jobs
    result = await db.execute(
        select(RepairOrder)
        .where(
            RepairOrder.tenant_id == tenant_id,
            RepairOrder.status.notin_(["complete"]),
        )
        .options(selectinload(RepairOrder.assigned_tech))
        .order_by(RepairOrder.intake_date.asc())
    )
    open_jobs = result.scalars().all()

    # Group by status
    jobs_by_status: dict[str, list] = defaultdict(list)
    for job in open_jobs:
        jobs_by_status[job.status].append(job)

    # Ready for pickup count (separate bucket)
    ready_count = len(jobs_by_status.get("ready_for_pickup", []))
    open_count = sum(len(jobs_by_status.get(s, [])) for s in ACTIVE_STATUSES)

    # Completed today
    completed_result = await db.execute(
        select(func.count(RepairOrder.id)).where(
            RepairOrder.tenant_id == tenant_id,
            RepairOrder.status == "complete",
            func.date(RepairOrder.completed_at) == today,
        )
    )
    completed_today = completed_result.scalar() or 0

    return templates.TemplateResponse(
        "auto_shop/dashboard.html",
        _template_ctx(
            request,
            jobs_by_status=jobs_by_status,
            active_statuses=ACTIVE_STATUSES,
            open_count=open_count,
            ready_count=ready_count,
            completed_today=completed_today,
            today=today,
        ),
    )


# ── job list ──────────────────────────────────────────────────────────────────

@router.get("/jobs")
async def jobs_list(
    request: Request,
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id

    query = (
        select(RepairOrder)
        .where(RepairOrder.tenant_id == tenant_id)
        .options(selectinload(RepairOrder.assigned_tech))
        .order_by(RepairOrder.created_at.desc())
    )
    if status_filter and status_filter in VALID_STATUSES:
        query = query.where(RepairOrder.status == status_filter)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return templates.TemplateResponse(
        "auto_shop/jobs_list.html",
        _template_ctx(request, jobs=jobs, status_filter=status_filter or ""),
    )


# ── create job ────────────────────────────────────────────────────────────────

@router.get("/jobs/new")
async def job_create_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id

    techs_result = await db.execute(
        select(User)
        .where(User.tenant_id == tenant_id, User.is_active == True)
        .order_by(User.name)
    )
    techs = techs_result.scalars().all()

    return templates.TemplateResponse(
        "auto_shop/job_create.html",
        _template_ctx(request, techs=techs),
    )


@router.post("/jobs/new")
async def job_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id
    form = await request.form()

    ticket_number = await _generate_ticket_number(db, tenant_id)

    mileage_raw = form.get("vehicle_mileage", "").strip()
    mileage = int(mileage_raw) if mileage_raw.isdigit() else None

    est_raw = form.get("estimated_completion", "").strip()
    estimated_completion = None
    if est_raw:
        try:
            estimated_completion = datetime.strptime(est_raw, "%Y-%m-%d").date()
        except ValueError:
            pass

    job = RepairOrder(
        id=str(uuid.uuid4()),
        ticket_number=ticket_number,
        vehicle_make=form.get("vehicle_make") or None,
        vehicle_model=form.get("vehicle_model") or None,
        vehicle_year=form.get("vehicle_year") or None,
        vehicle_color=form.get("vehicle_color") or None,
        vehicle_vin=form.get("vehicle_vin") or None,
        vehicle_license_plate=form.get("vehicle_license_plate") or None,
        vehicle_mileage=mileage,
        customer_name=form.get("customer_name", "").strip(),
        customer_phone=form.get("customer_phone") or None,
        customer_email=form.get("customer_email") or None,
        description=form.get("description") or None,
        internal_notes=form.get("internal_notes") or None,
        status="new_arrival",
        assigned_tech_id=form.get("assigned_tech_id") or None,
        estimated_completion=estimated_completion,
        payment_type=form.get("payment_type") or None,
        claim_number=form.get("claim_number") or None,
        tenant_id=tenant_id,
    )
    db.add(job)
    await db.flush()

    # Initial status log entry
    log = RepairOrderStatusLog(
        id=str(uuid.uuid4()),
        repair_order_id=job.id,
        old_status=None,
        new_status="new_arrival",
        notes="Job created",
        changed_by_id=user.id,
        tenant_id=tenant_id,
    )
    db.add(log)
    await db.commit()

    return RedirectResponse(url=f"/auto_shop/admin/jobs/{job.id}", status_code=303)


# ── job detail ────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}")
async def job_detail(
    request: Request,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id

    result = await db.execute(
        select(RepairOrder)
        .where(RepairOrder.id == job_id, RepairOrder.tenant_id == tenant_id)
        .options(
            selectinload(RepairOrder.assigned_tech),
            selectinload(RepairOrder.photos).selectinload(RepairOrderPhoto.uploaded_by),
            selectinload(RepairOrder.status_logs).selectinload(RepairOrderStatusLog.changed_by),
            selectinload(RepairOrder.payments),
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse(url="/auto_shop/admin/jobs", status_code=303)

    techs_result = await db.execute(
        select(User)
        .where(User.tenant_id == tenant_id, User.is_active == True)
        .order_by(User.name)
    )
    techs = techs_result.scalars().all()

    return templates.TemplateResponse(
        "auto_shop/job_detail.html",
        _template_ctx(request, job=job, techs=techs, today=date.today()),
    )


# ── edit job info ─────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/edit")
async def job_edit(
    request: Request,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id
    form = await request.form()

    result = await db.execute(
        select(RepairOrder).where(
            RepairOrder.id == job_id, RepairOrder.tenant_id == tenant_id
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse(url="/auto_shop/admin/jobs", status_code=303)

    mileage_raw = form.get("vehicle_mileage", "").strip()
    est_raw = form.get("estimated_completion", "").strip()

    job.vehicle_make = form.get("vehicle_make") or None
    job.vehicle_model = form.get("vehicle_model") or None
    job.vehicle_year = form.get("vehicle_year") or None
    job.vehicle_color = form.get("vehicle_color") or None
    job.vehicle_vin = form.get("vehicle_vin") or None
    job.vehicle_license_plate = form.get("vehicle_license_plate") or None
    job.vehicle_mileage = int(mileage_raw) if mileage_raw.isdigit() else None
    job.customer_name = form.get("customer_name", "").strip() or job.customer_name
    job.customer_phone = form.get("customer_phone") or None
    job.customer_email = form.get("customer_email") or None
    job.description = form.get("description") or None
    job.internal_notes = form.get("internal_notes") or None
    job.assigned_tech_id = form.get("assigned_tech_id") or None
    job.payment_type = form.get("payment_type") or None
    job.claim_number = form.get("claim_number") or None

    def _parse_decimal(key: str):
        raw = form.get(key, "").strip()
        try:
            return float(raw) if raw else None
        except ValueError:
            return None

    job.total_estimate = _parse_decimal("total_estimate")
    job.supplement_1 = _parse_decimal("supplement_1")
    job.supplement_2 = _parse_decimal("supplement_2")
    job.supplement_3 = _parse_decimal("supplement_3")
    job.supplement_4 = _parse_decimal("supplement_4")
    job.deductible = _parse_decimal("deductible")
    job.updated_at = datetime.utcnow()

    if est_raw:
        try:
            job.estimated_completion = datetime.strptime(est_raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    else:
        job.estimated_completion = None

    await db.commit()
    return RedirectResponse(url=f"/auto_shop/admin/jobs/{job_id}", status_code=303)


# ── status change ─────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/status")
async def job_update_status(
    request: Request,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id
    form = await request.form()
    new_status = form.get("new_status", "").strip()
    notes = form.get("notes", "").strip() or None
    notify_customer = "notify_customer" in form

    if new_status not in VALID_STATUSES:
        return RedirectResponse(url=f"/auto_shop/admin/jobs/{job_id}", status_code=303)

    result = await db.execute(
        select(RepairOrder).where(
            RepairOrder.id == job_id, RepairOrder.tenant_id == tenant_id
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse(url="/auto_shop/admin/jobs", status_code=303)

    old_status = job.status
    job.status = new_status
    job.updated_at = datetime.utcnow()

    if new_status == "complete":
        job.completed_at = datetime.utcnow()

    sms_sent = False
    if notify_customer:
        sms_sent = _send_status_sms(job, new_status)

    log = RepairOrderStatusLog(
        id=str(uuid.uuid4()),
        repair_order_id=job.id,
        old_status=old_status,
        new_status=new_status,
        notes=notes,
        changed_by_id=user.id,
        sms_sent=sms_sent,
        tenant_id=tenant_id,
    )
    db.add(log)
    await db.commit()

    return RedirectResponse(url=f"/auto_shop/admin/jobs/{job_id}", status_code=303)


# ── drag-and-drop move (JSON) ─────────────────────────────────────────────────

@router.post("/jobs/{job_id}/move")
async def job_move(
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    body = await request.json()
    new_status = (body.get("status") or "").strip()

    if new_status not in VALID_STATUSES:
        return JSONResponse({"ok": False, "error": "invalid status"}, status_code=400)

    result = await db.execute(
        select(RepairOrder).where(
            RepairOrder.id == job_id, RepairOrder.tenant_id == user.tenant_id
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    old_status = job.status
    if old_status == new_status:
        return JSONResponse({"ok": True})

    job.status = new_status
    job.updated_at = datetime.utcnow()
    if new_status == "complete":
        job.completed_at = datetime.utcnow()

    log = RepairOrderStatusLog(
        id=str(uuid.uuid4()),
        repair_order_id=job.id,
        old_status=old_status,
        new_status=new_status,
        notes="Moved via board",
        changed_by_id=user.id,
        sms_sent=False,
        tenant_id=user.tenant_id,
    )
    db.add(log)
    await db.commit()

    return JSONResponse({"ok": True})


# ── photo upload ──────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/photos")
async def job_upload_photo(
    request: Request,
    job_id: str,
    file: UploadFile = File(...),
    caption: str = Form(""),
    category: str = Form("intake"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id

    result = await db.execute(
        select(RepairOrder).where(
            RepairOrder.id == job_id, RepairOrder.tenant_id == tenant_id
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse(url="/auto_shop/admin/jobs", status_code=303)

    ext = os.path.splitext(file.filename or "photo.jpg")[1].lower() or ".jpg"
    safe_name = f"{uuid.uuid4()}{ext}"
    dest = os.path.join(PHOTO_DIR, safe_name)

    with open(dest, "wb") as buf:
        shutil.copyfileobj(file.file, buf)

    photo = RepairOrderPhoto(
        id=str(uuid.uuid4()),
        repair_order_id=job.id,
        filename=safe_name,
        original_filename=file.filename or safe_name,
        caption=caption.strip() or None,
        category=category or "intake",
        uploaded_by_id=user.id,
        tenant_id=tenant_id,
    )
    db.add(photo)
    await db.commit()

    return RedirectResponse(url=f"/auto_shop/admin/jobs/{job_id}", status_code=303)


# ── payments ─────────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/payments")
async def job_add_payment(
    request: Request,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id
    form = await request.form()

    result = await db.execute(
        select(RepairOrder).where(RepairOrder.id == job_id, RepairOrder.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        return RedirectResponse(url="/auto_shop/admin/jobs", status_code=303)

    amount_raw = form.get("amount", "").strip()
    try:
        amount = float(amount_raw)
    except ValueError:
        return RedirectResponse(url=f"/auto_shop/admin/jobs/{job_id}", status_code=303)

    date_raw = form.get("date_received", "").strip()
    try:
        date_received = datetime.strptime(date_raw, "%Y-%m-%d").date() if date_raw else date.today()
    except ValueError:
        date_received = date.today()

    payment = RepairOrderPayment(
        id=str(uuid.uuid4()),
        repair_order_id=job_id,
        payment_method=form.get("payment_method", "cash"),
        amount=amount,
        date_received=date_received,
        notes=form.get("notes", "").strip() or None,
        tenant_id=tenant_id,
    )
    db.add(payment)
    await db.commit()

    return RedirectResponse(url=f"/auto_shop/admin/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/payments/{payment_id}/delete")
async def job_delete_payment(
    job_id: str,
    payment_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    result = await db.execute(
        select(RepairOrderPayment).where(
            RepairOrderPayment.id == payment_id,
            RepairOrderPayment.repair_order_id == job_id,
            RepairOrderPayment.tenant_id == user.tenant_id,
        )
    )
    payment = result.scalar_one_or_none()
    if payment:
        await db.delete(payment)
        await db.commit()

    return RedirectResponse(url=f"/auto_shop/admin/jobs/{job_id}", status_code=303)


# ── delete photo ──────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/photos/{photo_id}/delete")
async def job_delete_photo(
    request: Request,
    job_id: str,
    photo_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id

    result = await db.execute(
        select(RepairOrderPhoto).where(
            RepairOrderPhoto.id == photo_id,
            RepairOrderPhoto.tenant_id == tenant_id,
            RepairOrderPhoto.repair_order_id == job_id,
        )
    )
    photo = result.scalar_one_or_none()
    if photo:
        disk_path = os.path.join(PHOTO_DIR, photo.filename)
        if os.path.exists(disk_path):
            os.remove(disk_path)
        await db.delete(photo)
        await db.commit()

    return RedirectResponse(url=f"/auto_shop/admin/jobs/{job_id}", status_code=303)


# ── financials ────────────────────────────────────────────────────────────────

@router.get("/financials")
async def financials(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id
    today = date.today()
    week_start = today - timedelta(days=today.weekday())   # Monday
    month_start = today.replace(day=1)

    # ── period totals ─────────────────────────────────────────────────────────
    async def _sum(extra_filters):
        r = await db.execute(
            select(func.coalesce(func.sum(RepairOrderPayment.amount), 0))
            .where(RepairOrderPayment.tenant_id == tenant_id, *extra_filters)
        )
        return float(r.scalar())

    week_total  = await _sum([RepairOrderPayment.date_received >= week_start])
    month_total = await _sum([RepairOrderPayment.date_received >= month_start])
    all_time    = await _sum([])

    # ── by payment method ─────────────────────────────────────────────────────
    method_res = await db.execute(
        select(
            RepairOrderPayment.payment_method,
            func.sum(RepairOrderPayment.amount).label("total"),
            func.count(RepairOrderPayment.id).label("count"),
        )
        .where(RepairOrderPayment.tenant_id == tenant_id)
        .group_by(RepairOrderPayment.payment_method)
        .order_by(func.sum(RepairOrderPayment.amount).desc())
    )
    by_method = method_res.all()

    # ── jobs with financial data (balance tracking) ───────────────────────────
    jobs_res = await db.execute(
        select(RepairOrder)
        .where(
            RepairOrder.tenant_id == tenant_id,
            RepairOrder.total_estimate != None,
        )
        .options(selectinload(RepairOrder.payments))
        .order_by(RepairOrder.intake_date.desc())
    )
    all_jobs = jobs_res.scalars().all()

    job_rows = []
    total_outstanding = 0.0
    total_estimate_sum = 0.0

    for job in all_jobs:
        sups = sum(float(getattr(job, f"supplement_{i}") or 0) for i in range(1, 5))
        grand_total = float(job.total_estimate or 0) + sups
        collected   = sum(float(p.amount) for p in job.payments)
        balance     = grand_total - collected
        total_estimate_sum += grand_total
        if balance > 0:
            total_outstanding += balance
        job_rows.append({
            "job":         job,
            "grand_total": grand_total,
            "collected":   collected,
            "balance":     balance,
        })

    # ── recent payments ───────────────────────────────────────────────────────
    recent_res = await db.execute(
        select(RepairOrderPayment)
        .where(RepairOrderPayment.tenant_id == tenant_id)
        .options(selectinload(RepairOrderPayment.repair_order))
        .order_by(
            RepairOrderPayment.date_received.desc(),
            RepairOrderPayment.created_at.desc(),
        )
        .limit(25)
    )
    recent_payments = recent_res.scalars().all()

    return templates.TemplateResponse(
        "auto_shop/financials.html",
        _template_ctx(
            request,
            today=today,
            week_total=week_total,
            month_total=month_total,
            all_time=all_time,
            total_outstanding=total_outstanding,
            total_estimate_sum=total_estimate_sum,
            by_method=by_method,
            job_rows=job_rows,
            recent_payments=recent_payments,
            payment_method_labels=PAYMENT_METHOD_LABELS,
        ),
    )


# ── send tracking link email ──────────────────────────────────────────────────

@router.post("/jobs/{job_id}/send-tracking-email")
async def send_tracking_link_email(
    request: Request,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    from app.models.tenant import Tenant
    from app.utils.email_service import send_tracking_email

    result = await db.execute(
        select(RepairOrder).where(
            RepairOrder.id == job_id, RepairOrder.tenant_id == user.tenant_id
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse(url="/auto_shop/admin/jobs", status_code=303)

    if not job.customer_email:
        return RedirectResponse(
            url=f"/auto_shop/admin/jobs/{job_id}?error=No+customer+email+on+file",
            status_code=303,
        )

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = tenant_result.scalar_one_or_none()

    base_url = str(request.base_url).rstrip("/")
    tracking_url = f"{base_url}/auto_shop/track/{job.tracking_token}"

    outcome = send_tracking_email(tenant=tenant, job=job, tracking_url=tracking_url)

    if outcome["success"]:
        return RedirectResponse(
            url=f"/auto_shop/admin/jobs/{job_id}?success=Tracking+link+emailed+to+customer",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/auto_shop/admin/jobs/{job_id}?error={outcome['message'].replace(' ', '+')}",
        status_code=303,
    )


# ── delete job ────────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/delete")
async def job_delete(
    request: Request,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id

    result = await db.execute(
        select(RepairOrder).where(
            RepairOrder.id == job_id, RepairOrder.tenant_id == tenant_id
        ).options(selectinload(RepairOrder.photos))
    )
    job = result.scalar_one_or_none()
    if job:
        for photo in job.photos:
            disk_path = os.path.join(PHOTO_DIR, photo.filename)
            if os.path.exists(disk_path):
                os.remove(disk_path)
        await db.delete(job)
        await db.commit()

    return RedirectResponse(url="/auto_shop/admin/jobs", status_code=303)
