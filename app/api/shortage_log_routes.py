from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime

from app.db import get_db
from app.models.shortage_log import ShortageLog
from app.auth.dependencies import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# 📋 GET: Show shortage board + form (scoped)
@router.get("/shortage-form")
async def shortage_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    result = await db.execute(
        select(ShortageLog)
        .where(ShortageLog.tenant_id == user.tenant_id)
        .order_by(ShortageLog.timestamp.desc())
    )
    shortages = result.scalars().all()

    return templates.TemplateResponse("shortage_form.html", {
        "request": request,
        "shortages": shortages,
        "user": user
    })


# ➕ POST: Add new shortage (scoped)
@router.post("/shortage-form")
async def submit_shortage(
    request: Request,
    note: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    log = ShortageLog(
        note=note,
        is_resolved=False,
        timestamp=datetime.utcnow(),
        tenant_id=user.tenant_id
    )
    db.add(log)
    await db.commit()

    return RedirectResponse("/shortage-form", status_code=302)


# ✅ POST: Resolve a shortage (scoped to tenant)
@router.post("/resolve-shortage")
async def resolve_shortage(
    request: Request,
    shortage_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    result = await db.execute(
        select(ShortageLog).where(
            ShortageLog.id == shortage_id,
            ShortageLog.tenant_id == user.tenant_id
        )
    )
    log = result.scalar_one_or_none()

    if log:
        log.is_resolved = True
        await db.commit()

    return RedirectResponse("/shortage-form", status_code=302)
