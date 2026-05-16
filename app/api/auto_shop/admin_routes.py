"""
Auto Shop Admin Routes

Manage repair orders: create, update, status changes, photo uploads.
"""
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from typing import Optional
from datetime import datetime, date
from collections import defaultdict
import uuid
import os
import shutil

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.user import User
from app.models.auto_shop import (
    RepairOrder,
    RepairOrderPhoto,
    RepairOrderStatusLog,
    VALID_STATUSES,
    STATUS_LABELS,
    STATUS_BADGE_COLORS,
    STATUS_SMS_MESSAGES,
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
        **kwargs,
    }


# ── dashboard ─────────────────────────────────────────────────────────────────

ACTIVE_STATUSES = [s for s in VALID_STATUSES if s not in ("completed", "ready_for_pickup")]

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
            RepairOrder.status.notin_(["completed"]),
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
            RepairOrder.status == "completed",
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
        status="intake",
        assigned_tech_id=form.get("assigned_tech_id") or None,
        estimated_completion=estimated_completion,
        tenant_id=tenant_id,
    )
    db.add(job)
    await db.flush()

    # Initial status log entry
    log = RepairOrderStatusLog(
        id=str(uuid.uuid4()),
        repair_order_id=job.id,
        old_status=None,
        new_status="intake",
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
        _template_ctx(request, job=job, techs=techs),
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

    if new_status == "completed":
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
