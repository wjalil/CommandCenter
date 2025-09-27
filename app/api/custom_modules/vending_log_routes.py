from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import uuid, shutil, os
from app.models.custom_modules.machine import Machine
from app.models.custom_modules.vending_log import VendingLog
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.db import get_db
from sqlalchemy.future import select
from app.core.constants import UPLOAD_PATHS
from typing import Optional
from app.utils.security import validate_and_read_image, generate_safe_filename

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = UPLOAD_PATHS['vending_logs']

# 📝 Internal form: for staff/admin use
@router.get("/vending/log")
async def show_vending_log_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(select(Machine))
    machines = result.scalars().all()
    return templates.TemplateResponse("custom_modules/vending_log_form.html", {
        "request": request,
        "machines": machines,
    })

@router.post("/vending/log")
async def submit_vending_log(
    request: Request,
    db: AsyncSession = Depends(get_db),
    notes: str = Form(""),
    machine_id: str = Form(...),
    photo: UploadFile = File(None),
    current_user: User = Depends(get_current_user),
):
    photo_filename = None
    if photo:
        contents = await validate_and_read_image(photo)
        photo_filename = generate_safe_filename(photo.filename)
        path = os.path.join(UPLOAD_DIR, photo_filename)
        with open(path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)

    new_log = VendingLog(
        notes=notes,
        photo_filename=photo_filename,
        submitter_id=current_user.id,
        machine_id=machine_id,
        issue_type="internal",
        source="internal"
    )
    try:
        db.add(new_log)
        await db.commit()
        success_msg = "Log submitted successfully!"
        redirect_url = str(request.url_for("show_vending_log_form")) + f"?success={quote(success_msg)}"
        print("🔁 Redirecting to:", redirect_url)  # ← sanity check in logs
        return RedirectResponse(url=redirect_url, status_code=303)
    except Exception:
        await db.rollback()
        err = "Could not save log. Please try again."
        redirect_url = str(request.url_for("show_vending_log_form")) + f"?error={quote(err)}"
        return RedirectResponse(url=redirect_url, status_code=303)

    return RedirectResponse(
    url=str(request.url_for("show_vending_log_form")) + "?success=Log%20submitted%20successfully!",
    status_code=303,
    )

# 🌐 Public QR form: no login required
@router.get("/vending/form", response_class=HTMLResponse)
async def vending_qr_board(
    request: Request,
    machine_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
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

    return templates.TemplateResponse("custom_modules/vending_qr_forms.html", {
        "request": request,
        "machine": machine,
        "logs": logs
    })

@router.post("/vending/form")
async def submit_vending_form(
    request: Request,
    machine_id: str = Form(...),
    issue_type: str = Form(...),
    notes: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db)
):
    photo_filename = None

    if photo and photo.filename:
        contents = await validate_and_read_image(photo)
        photo_filename = generate_safe_filename(photo.filename)
        upload_path = os.path.join(UPLOAD_PATHS["vending_qr_photos"], photo_filename)

        with open(upload_path, "wb") as buffer:
            buffer.write(contents)

    new_log = VendingLog(
        machine_id=machine_id,
        issue_type=issue_type,
        notes=notes,
        email=email,
        photo_filename=photo_filename,
        timestamp=datetime.utcnow(),
        source="qr"
    )
    db.add(new_log)
    await db.commit()

    return RedirectResponse(
        url=f"/vending/form?machine_id={machine_id}&success=true",
        status_code=303
    )
