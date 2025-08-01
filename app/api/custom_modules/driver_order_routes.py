from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime
import uuid
import os

from app.db import get_db
from app.models.custom_modules.driver_order import DriverOrder
from app.auth.dependencies import get_current_user
from app.core.constants import UPLOAD_PATHS

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = UPLOAD_PATHS["driver_orders"]


# 🧾 GET: Form + Logs
@router.get("/modules/driver_order", response_class=HTMLResponse)
async def driver_order_module(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    result = await db.execute(
        select(DriverOrder)
        .where(DriverOrder.tenant_id == user.tenant_id)
        .order_by(DriverOrder.timestamp.desc())
    )
    logs = result.scalars().all()
    return templates.TemplateResponse("custom_modules/driver_order.html", {"request": request, "logs": logs})


# 📝 POST: Submit a New Log
@router.post("/modules/driver_order/submit")
async def submit_driver_order(
    request: Request,
    notes: str = Form(""),
    photo: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    photo_filename = None

    if photo:
        ext = os.path.splitext(photo.filename)[-1]
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        photo_path = os.path.join(UPLOAD_DIR, unique_filename)
        with open(photo_path, "wb") as f:
            f.write(await photo.read())
        photo_filename = unique_filename

    log = DriverOrder(
        notes=notes,
        timestamp=datetime.utcnow(),
        photo_filename=photo_filename,
        tenant_id=user.tenant_id  # ✅ set tenant
    )
    db.add(log)
    await db.commit()

    return RedirectResponse("/modules/driver_order", status_code=303)


# ✅ POST: Mark Resolved
@router.post("/modules/driver_order/resolve")
async def resolve_driver_order(
    request: Request,
    log_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    result = await db.execute(
        select(DriverOrder)
        .where(DriverOrder.id == log_id)
        .where(DriverOrder.tenant_id == user.tenant_id)  # ✅ scope resolution
    )
    log = result.scalar_one_or_none()
    if log:
        log.is_resolved = True
        await db.commit()

    referer = request.headers.get("referer", "/modules/driver_order")
    return RedirectResponse(referer, status_code=303)
