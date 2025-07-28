from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse,HTMLResponse
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

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = UPLOAD_PATHS['vending_logs']

@router.get("/vending/log")
async def show_vending_log_form(request: Request, db: AsyncSession = Depends(get_db)):
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
    machine_id: str = Form(...),  # 👈 add this
    photo: UploadFile = File(None),
    current_user: User = Depends(get_current_user),
):
    photo_filename = None
    if photo:
        ext = photo.filename.split(".")[-1]
        photo_filename = f"{uuid.uuid4()}.{ext}"
        path = os.path.join(UPLOAD_DIR, photo_filename)
        with open(path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)

    print("🔧 [DEBUG] Submitting internal vending log with issue_type='internal'")  # 👈 Add this

    new_log = VendingLog(
        notes=notes,
        photo_filename=photo_filename,
        submitter_id=current_user.id,
        machine_id=machine_id,
        issue_type="internal",
        source="internal"
    )
    db.add(new_log)
    await db.commit()

    return RedirectResponse("/worker/shifts", status_code=302)

@router.get("/vending/form", response_class=HTMLResponse)
async def vending_qr_board(request: Request, machine_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
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

    # ✅ Handle photo upload
    if photo and photo.filename:
        ext = os.path.splitext(photo.filename)[1]
        photo_filename = f"vending_{uuid.uuid4().hex}{ext}"
        upload_path = os.path.join(UPLOAD_PATHS["vending_qr_photos"], photo_filename)

        with open(upload_path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)

    # ✅ Create VendingLog entry
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

    # ✅ Redirect to thank-you page or confirmation
    return RedirectResponse(
    url=f"/vending/form?machine_id={machine_id}",
    status_code=303
    )
