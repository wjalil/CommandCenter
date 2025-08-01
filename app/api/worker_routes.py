from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from collections import defaultdict
from datetime import timedelta

from app.db import get_db
from app.models.shift import Shift
from app.models.task import Task, TaskTemplate
from app.models.user import User
from app.auth.dependencies import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/worker/shifts")
async def worker_shift_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    # 🧠 Ensure only workers can view this page
    if user.role != "worker":
        return templates.TemplateResponse("unauthorized.html", {"request": request})

    result = await db.execute(
        select(Shift)
        .where(Shift.assigned_worker_id == user.id)
        .where(Shift.tenant_id == user.tenant_id)
        .order_by(Shift.start_time)
        .options(
            selectinload(Shift.tasks).selectinload(Task.template).selectinload(TaskTemplate.items),
            selectinload(Shift.submissions)
        )
    )
    shifts = result.scalars().all()

    weekly_shifts = defaultdict(list)
    weekly_hours = defaultdict(float)
    shift_alerts = {}

    for shift in shifts:
        week_start = shift.start_time - timedelta(days=shift.start_time.weekday())
        week_label = week_start.strftime("%B %d, %Y")
        weekly_shifts[week_label].append(shift)

        duration = (shift.end_time - shift.start_time).total_seconds() / 3600
        weekly_hours[week_label] += duration

        total_items = sum(len(task.template.items) for task in shift.tasks if task.template)
        completed = len(shift.submissions)
        pending = total_items - completed
        shift_alerts[shift.id] = {"pending": pending, "total": total_items}

    return templates.TemplateResponse("worker_shifts.html", {
        "request": request,
        "weekly_shifts": dict(weekly_shifts),
        "weekly_hours": dict(weekly_hours),
        "worker_id": user.id,
        "worker_name": user.name,
        "shift_alerts": shift_alerts,
    })

@router.get("/worker/{worker_id}/shifts")
async def worker_shift_view(
    worker_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    session_user_id = request.session.get("user_id")
    session_tenant_id = request.session.get("tenant_id")

    # 🔒 Validate session user matches URL param
    if session_user_id != worker_id:
        return RedirectResponse(url="/", status_code=302)

    # 🔐 Load worker and validate tenant match
    worker = await db.get(User, worker_id)
    if not worker or worker.tenant_id != session_tenant_id:
        return RedirectResponse(url="/", status_code=302)

    result = await db.execute(
        select(Shift)
        .where(Shift.assigned_worker_id == worker_id)
        .where(Shift.tenant_id == session_tenant_id)
        .order_by(Shift.start_time)
        .options(
            selectinload(Shift.tasks).selectinload(Task.template).selectinload(TaskTemplate.items),
            selectinload(Shift.submissions)
        )
    )
    shifts = result.scalars().all()

    weekly_shifts = defaultdict(list)
    weekly_hours = defaultdict(float)
    shift_alerts = {}

    for shift in shifts:
        week_start = shift.start_time - timedelta(days=shift.start_time.weekday())
        week_label = week_start.strftime("%B %d, %Y")
        weekly_shifts[week_label].append(shift)

        duration = (shift.end_time - shift.start_time).total_seconds() / 3600
        weekly_hours[week_label] += duration

        total_items = sum(len(task.template.items) for task in shift.tasks if task.template)
        completed = len(shift.submissions)
        pending = total_items - completed
        shift_alerts[shift.id] = {"pending": pending, "total": total_items}

    return templates.TemplateResponse("worker_shifts.html", {
        "request": request,
        "weekly_shifts": dict(weekly_shifts),
        "weekly_hours": dict(weekly_hours),
        "worker_id": worker_id,
        "worker_name": worker.name,
        "shift_alerts": shift_alerts,
    })