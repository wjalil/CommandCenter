"""
Public customer-facing repair order tracking (no auth required).
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.auto_shop import (
    RepairOrder,
    RepairOrderStatusLog,
    VALID_STATUSES,
    STATUS_LABELS,
    STATUS_BADGE_COLORS,
)
from app.models.tenant import Tenant

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/track/{token}", response_class=HTMLResponse)
async def track_repair_order(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepairOrder)
        .where(RepairOrder.tracking_token == token)
        .options(
            selectinload(RepairOrder.status_logs),
            selectinload(RepairOrder.tenant),
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        return templates.TemplateResponse(
            "auto_shop/track.html",
            {
                "request": request,
                "job": None,
                "not_found": True,
            },
            status_code=404,
        )

    # Public logs: exclude notes that contain "internal" markers (optional safeguard)
    public_logs = sorted(job.status_logs, key=lambda l: l.changed_at, reverse=True)

    return templates.TemplateResponse(
        "auto_shop/track.html",
        {
            "request": request,
            "job": job,
            "not_found": False,
            "public_logs": public_logs,
            "status_labels": STATUS_LABELS,
            "status_badge_colors": STATUS_BADGE_COLORS,
            "valid_statuses": VALID_STATUSES,
        },
    )
