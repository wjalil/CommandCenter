from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import datetime
import uuid
import os
import shutil

from app.db import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.models.auto_shop import (
    RepairOrder,
    RepairOrderPhoto,
    RepairOrderStatusLog,
    VALID_STATUSES,
    STATUS_LABELS,
    STATUS_BADGE_COLORS,
)
from app.core.constants import UPLOAD_PATHS

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PHOTO_DIR = UPLOAD_PATHS["auto_shop_photos"]


def _ctx(request: Request, **kwargs) -> dict:
    return {
        "request": request,
        "status_labels": STATUS_LABELS,
        "status_badge_colors": STATUS_BADGE_COLORS,
        "valid_statuses": VALID_STATUSES,
        **kwargs,
    }


async def _get_job(db: AsyncSession, job_id: str, tenant_id: int):
    result = await db.execute(
        select(RepairOrder)
        .where(RepairOrder.id == job_id, RepairOrder.tenant_id == tenant_id)
        .options(
            selectinload(RepairOrder.assigned_tech),
            selectinload(RepairOrder.photos).selectinload(RepairOrderPhoto.uploaded_by),
            selectinload(RepairOrder.status_logs).selectinload(RepairOrderStatusLog.changed_by),
        )
    )
    return result.scalar_one_or_none()


@router.get("/jobs")
async def worker_jobs_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(RepairOrder)
        .where(
            RepairOrder.tenant_id == user.tenant_id,
            RepairOrder.status.notin_(["complete"]),
        )
        .options(selectinload(RepairOrder.assigned_tech))
        .order_by(RepairOrder.created_at.desc())
    )
    jobs = result.scalars().all()

    return templates.TemplateResponse(
        "auto_shop/worker_jobs_list.html",
        _ctx(request, jobs=jobs, worker_name=user.name),
    )


@router.get("/jobs/{job_id}")
async def worker_job_detail(
    request: Request,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = await _get_job(db, job_id, user.tenant_id)
    if not job:
        return RedirectResponse(url="/auto_shop/worker/jobs", status_code=303)

    return templates.TemplateResponse(
        "auto_shop/worker_job_detail.html",
        _ctx(request, job=job, worker_name=user.name),
    )


@router.post("/jobs/{job_id}/status")
async def worker_update_status(
    request: Request,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    form = await request.form()
    new_status = form.get("new_status", "").strip()
    notes = form.get("notes", "").strip() or None

    if new_status not in VALID_STATUSES:
        return RedirectResponse(url=f"/auto_shop/worker/jobs/{job_id}", status_code=303)

    result = await db.execute(
        select(RepairOrder).where(
            RepairOrder.id == job_id, RepairOrder.tenant_id == user.tenant_id
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse(url="/auto_shop/worker/jobs", status_code=303)

    old_status = job.status
    job.status = new_status
    job.updated_at = datetime.utcnow()
    if new_status == "complete":
        job.completed_at = datetime.utcnow()

    log = RepairOrderStatusLog(
        id=str(uuid.uuid4()),
        repair_order_id=job.id,
        old_status=old_status,
        new_status=new_status,
        notes=notes,
        changed_by_id=user.id,
        sms_sent=False,
        tenant_id=user.tenant_id,
    )
    db.add(log)
    await db.commit()

    return RedirectResponse(url=f"/auto_shop/worker/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/note")
async def worker_add_note(
    request: Request,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    form = await request.form()
    note_text = form.get("note", "").strip()

    if not note_text:
        return RedirectResponse(url=f"/auto_shop/worker/jobs/{job_id}", status_code=303)

    result = await db.execute(
        select(RepairOrder).where(
            RepairOrder.id == job_id, RepairOrder.tenant_id == user.tenant_id
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse(url="/auto_shop/worker/jobs", status_code=303)

    log = RepairOrderStatusLog(
        id=str(uuid.uuid4()),
        repair_order_id=job.id,
        old_status=job.status,
        new_status=job.status,
        notes=note_text,
        changed_by_id=user.id,
        sms_sent=False,
        tenant_id=user.tenant_id,
    )
    db.add(log)
    await db.commit()

    return RedirectResponse(url=f"/auto_shop/worker/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/photos")
async def worker_upload_photo(
    request: Request,
    job_id: str,
    file: UploadFile = File(...),
    caption: str = Form(""),
    category: str = Form("progress"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(RepairOrder).where(
            RepairOrder.id == job_id, RepairOrder.tenant_id == user.tenant_id
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse(url="/auto_shop/worker/jobs", status_code=303)

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
        category=category or "progress",
        uploaded_by_id=user.id,
        tenant_id=user.tenant_id,
    )
    db.add(photo)
    await db.commit()

    return RedirectResponse(url=f"/auto_shop/worker/jobs/{job_id}", status_code=303)
