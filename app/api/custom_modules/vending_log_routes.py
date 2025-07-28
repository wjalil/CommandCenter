from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse
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

    new_log = VendingLog(
        notes=notes,
        photo_filename=photo_filename,
        submitter_id=current_user.id,
        machine_id=machine_id,
    )
    db.add(new_log)
    await db.commit()

    return RedirectResponse("/worker/shifts", status_code=302)
