from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import uuid, os
from urllib.parse import quote
from typing import Optional
from os import getenv

from app.models.custom_modules.machine import Machine
from app.models.custom_modules.vending_log import VendingLog
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.db import get_db
from sqlalchemy.future import select
from app.utils.security import validate_and_read_image, generate_safe_filename
from typing import Optional, List

# Spaces uploader
from app.utils.spaces import put_public_object

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# 📝 Internal form: for staff/admin use
@router.get("/vending/log")
async def show_vending_log_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Machine))
    machines = result.scalars().all()
    return templates.TemplateResponse(
        "custom_modules/vending_log_form.html",
        {
            "request": request,
            "machines": machines,
        },
    )


@router.post("/vending/log")
async def submit_vending_log(
    request: Request,
    db: AsyncSession = Depends(get_db),
    notes: str = Form(""),
    machine_id: str = Form(...),
    photos: List[UploadFile] = File(default_factory=list),
    next: Optional[str] = Form(None),  # <-- ADD THIS
    current_user: User = Depends(get_current_user),
):
    photo_keys: list[str] = []
    prefix = getenv("DO_SPACES_PREFIX", "prod").strip("/")

    for photo in photos or []:
        if not photo or not photo.filename:
            continue

        contents = await validate_and_read_image(photo)
        safe_name = generate_safe_filename(photo.filename)
        ext = os.path.splitext(safe_name)[1].lower() or ".jpg"

        key = (
            f"{prefix}/tenants/{current_user.tenant_id}/vending/internal/"
            f"{machine_id}/{uuid.uuid4().hex}{ext}"
        )

        await put_public_object(
            key=key,
            body=contents,
            content_type=photo.content_type,
        )
        photo_keys.append(key)

    photo_filename = ",".join(photo_keys) if photo_keys else None

    new_log = VendingLog(
        notes=notes,
        photo_filename=photo_filename,
        submitter_id=current_user.id,
        machine_id=machine_id,
        issue_type="internal",
        source="internal",
        timestamp=datetime.utcnow(),
    )

    try:
        db.add(new_log)
        await db.commit()

        success_msg = "Log submitted successfully!"
        redirect_base = next or str(request.url_for("show_vending_log_form"))
        redirect_url = f"{redirect_base}?success={quote(success_msg)}"
        return RedirectResponse(url=redirect_url, status_code=303)

    except Exception:
        await db.rollback()

        err = "Could not save log. Please try again."
        redirect_base = next or str(request.url_for("show_vending_log_form"))
        redirect_url = f"{redirect_base}?error={quote(err)}"
        return RedirectResponse(url=redirect_url, status_code=303)


# 🌐 Public QR form: no login required
@router.get("/vending/form", response_class=HTMLResponse)
async def vending_qr_board(
    request: Request,
    machine_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    machine = None
    logs = []
    if machine_id:
        result = await db.execute(select(Machine).where(Machine.id == machine_id))
        machine = result.scalar_one_or_none()

        if machine:
            result = await db.execute(
                select(VendingLog)
                .where(VendingLog.machine_id == machine.id)
                .where(VendingLog.source == "qr")
                .order_by(VendingLog.timestamp.desc())
            )
            logs = result.scalars().all()

    return templates.TemplateResponse(
        "custom_modules/vending_qr_forms.html",
        {
            "request": request,
            "machine": machine,
            "logs": logs,
        },
    )


@router.post("/vending/form")
async def submit_vending_form(
    request: Request,
    machine_id: str = Form(...),
    issue_type: str = Form(...),
    notes: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
):
    photo_filename = None
    prefix = getenv("DO_SPACES_PREFIX", "prod").strip("/")  # dev/prod support

    # ONLY CHANGE: save to Spaces instead of local disk
    if photo and photo.filename:
        contents = await validate_and_read_image(photo)
        safe_name = generate_safe_filename(photo.filename)
        ext = os.path.splitext(safe_name)[1].lower() or ".jpg"

        photo_filename = (
            f"{prefix}/public/vending/qr/"
            f"{machine_id}/{uuid.uuid4().hex}{ext}"
        )

        await put_public_object(
            key=photo_filename,
            body=contents,
            content_type=photo.content_type,
        )

    new_log = VendingLog(
        machine_id=machine_id,
        issue_type=issue_type,
        notes=notes,
        email=email,
        photo_filename=photo_filename,
        timestamp=datetime.utcnow(),
        source="qr",
    )
    db.add(new_log)
    await db.commit()

    return RedirectResponse(
        url=f"/vending/form?machine_id={machine_id}&success=true",
        status_code=303,
    )
