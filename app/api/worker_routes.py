from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from collections import defaultdict
from datetime import datetime, timedelta

from app.db import get_db
from app.models.shift import Shift
from app.models.task import Task, TaskTemplate, TaskItem
from app.models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/worker/{worker_id}/shifts")
async def worker_shift_view(worker_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Shift)
        .where(Shift.assigned_worker_id == worker_id)
        .order_by(Shift.start_time)
        .options(
        selectinload(Shift.tasks).selectinload(Task.template),
        selectinload(Shift.tasks).selectinload(Task.template).selectinload(TaskTemplate.items),
        selectinload(Shift.submissions)
        )
    )
    shifts = result.scalars().all()

    weekly_shifts = defaultdict(list)
    weekly_hours = defaultdict(float)
    shift_alerts = {}

    for shift in shifts:
        week_start = shift.start_time - timedelta(days=shift.start_time.weekday())  # Monday
        week_label = week_start.strftime("%B %d, %Y")  # e.g., "July 15, 2025"
        weekly_shifts[week_label].append(shift)

        # ⏱️ Calculate hours for this shift
        duration = (shift.end_time - shift.start_time).total_seconds() / 3600
        weekly_hours[week_label] += duration

        # 📋 Task alert logic
        total_items = sum(len(task.template.items) for task in shift.tasks if task.template)
        completed = len(shift.submissions)
        pending = total_items - completed
        shift_alerts[shift.id] = {"pending": pending, "total": total_items}

    worker = await db.get(User, worker_id)
    worker_name = worker.name if worker else "Unknown"

    return templates.TemplateResponse("worker_shifts.html", {
        "request": request,
        "weekly_shifts": dict(weekly_shifts),
        "weekly_hours": dict(weekly_hours),
        "worker_id": worker_id,
        "worker_name": worker_name,
        "shift_alerts": shift_alerts,
    })

