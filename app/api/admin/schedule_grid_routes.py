from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from datetime import datetime, date as dt_date, time as dt_time, timedelta
import uuid
from typing import Optional, Union, Literal
from pydantic import BaseModel

from app.db import get_db
from app.models.user import User
from app.models.shift import Shift
from app.utils.tenant import get_current_tenant_id
from app.auth.dependencies import get_current_admin_user


templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/admin/schedule", tags=["Schedule Grid"])

# ---------- helpers ----------
def monday_of(d: dt_date) -> dt_date:
    return d - timedelta(days=d.weekday())

def week_span(start_monday: dt_date):
    start = monday_of(start_monday)
    days = [start + timedelta(days=i) for i in range(7)]
    end_exclusive = days[-1] + timedelta(days=1)
    return start, days, end_exclusive

def parse_hhmm(s: str) -> dt_time:
    return datetime.strptime(s, "%H:%M").time()

def auto_label(worker_name: str, day: dt_date, start: dt_time, end: dt_time) -> str:
    wd = day.strftime("%a")
    return f"{worker_name} {wd} {start.strftime('%H:%M')}-{end.strftime('%H:%M')}"

# ---------- payload schemas (discriminated union) ----------
class DeleteOp(BaseModel):
    op: Literal["delete"]
    shift_id: str

class CreateOp(BaseModel):
    op: Literal["create"]
    worker_id: str
    date: str           # "YYYY-MM-DD"
    start: str          # "HH:MM"
    end: str            # "HH:MM"
    role: Optional[str] = None

class UpdateOp(CreateOp):
    op: Literal["update"]
    shift_id: str

ChangeOp = Union[DeleteOp, CreateOp, UpdateOp]

class BulkUpsertPayload(BaseModel):
    week_start: str
    changes: list[ChangeOp]

# ---------- pages ----------
@router.get("/grid")
async def schedule_grid_page(request: Request, user: User = Depends(get_current_admin_user)):
    today = datetime.now().date()
    current_monday = today - timedelta(days=today.weekday())
    # If you open on Sunday, jump to next Monday
    week_start = (current_monday + (timedelta(days=7) if today.weekday()==6 else timedelta(0))).isoformat()
    return templates.TemplateResponse("admin/schedule_grid.html", {"request": request, "week_start": week_start})

# ---------- data ----------
@router.get("/data")
async def get_schedule_data(
    request: Request,
    week_start: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id
    monday = dt_date.fromisoformat(week_start)
    start, days, end_excl = week_span(monday)

    workers = (await db.execute(
        select(User).where(User.tenant_id == tenant_id,User.role == "worker",User.is_active == True,).order_by(User.name)
    )).scalars().all()

    shifts = (await db.execute(
        select(Shift).where(
            Shift.tenant_id == tenant_id,
            Shift.date >= datetime.combine(start, dt_time.min),
            Shift.date <  datetime.combine(end_excl, dt_time.min),
        )
    )).scalars().all()

    days_iso = [d.isoformat() for d in days]
    cells = {str(w.id): {di: None for di in days_iso} for w in workers}
    for s in shifts:
        wid = s.assigned_worker_id
        if not wid:
            continue
        key = s.date.date().isoformat()
        if wid in cells and key in cells[wid]:
            cells[wid][key] = {
                "shift_id": str(s.id),
                "start": s.start_time.strftime("%H:%M"),
                "end": s.end_time.strftime("%H:%M"),
                "role": s.shift_type or None,
                "is_completed": bool(s.is_completed),
            }

    return {
        "week_start": start.isoformat(),
        "days": days_iso,
        "workers": [{"id": str(w.id), "name": w.name, "role": w.role} for w in workers],
        "cells": cells,
        "metadata": {"tenant_id": tenant_id, "timezone": "America/New_York"},
    }

# ---------- write ----------
@router.post("/bulk_upsert")
async def bulk_upsert(
    request: Request,
    payload: BulkUpsertPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = user.tenant_id

    worker_rows = (await db.execute(
        select(User.id, User.name).where(
            User.tenant_id == tenant_id,
            User.role == "worker",
            User.is_active == True,
        )
    )).all()

    worker_name_by_id = {str(i): n for (i, n) in worker_rows}

    created = updated = deleted = 0

    for change in payload.changes:
        if change.op == "delete":
            await db.execute(
                delete(Shift).where(Shift.id == change.shift_id, Shift.tenant_id == tenant_id)
            )
            deleted += 1
            continue

        # Common parse for create/update
        day = dt_date.fromisoformat(change.date)
        start_t = parse_hhmm(change.start)
        end_t   = parse_hhmm(change.end)
        if end_t <= start_t:
            raise HTTPException(422, detail=f"End must be after start: {change}")

        start_dt = datetime.combine(day, start_t)
        end_dt   = datetime.combine(day, end_t)

        # same-day overlap check
        same_day = (await db.execute(
            select(Shift).where(
                Shift.tenant_id == tenant_id,
                Shift.assigned_worker_id == change.worker_id,
                Shift.date >= datetime.combine(day, dt_time.min),
                Shift.date <  datetime.combine(day + timedelta(days=1), dt_time.min),
            )
        )).scalars().all()

        exclude_id = change.shift_id if change.op == "update" else None
        for s in same_day:
            if exclude_id and str(s.id) == exclude_id:
                continue
            if not (end_dt <= s.start_time or start_dt >= s.end_time):
                raise HTTPException(409, detail=f"Overlap for worker {change.worker_id} on {day.isoformat()}")

        if change.op == "update":
            await db.execute(
                update(Shift).where(
                    Shift.id == change.shift_id,
                    Shift.tenant_id == tenant_id
                ).values(
                    start_time=start_dt,
                    end_time=end_dt,
                    date=datetime.combine(day, dt_time(0,0)),
                    shift_type=change.role,
                    assigned_worker_id=change.worker_id,
                    label=auto_label(worker_name_by_id.get(change.worker_id, "Worker"), day, start_t, end_t),
                    is_filled=True
                )
            )
            updated += 1
        else:  # create
            new = Shift(
                id=str(uuid.uuid4()),
                label=auto_label(worker_name_by_id.get(change.worker_id, "Worker"), day, start_t, end_t),
                start_time=start_dt,
                end_time=end_dt,
                date=datetime.combine(day, dt_time(0,0)),
                tenant_id=tenant_id,
                is_filled=True,
                is_completed=False,
                is_recurring=False,
                shift_type=change.role,
                assigned_worker_id=change.worker_id,
                recurring_until=None,
                is_seed=False,
                recurring_group_id=None
            )
            db.add(new)
            created += 1

    await db.commit()
    return {"created": created, "updated": updated, "deleted": deleted}

@router.get("/timeslots")
async def timeslots_page(request: Request, user: User = Depends(get_current_admin_user)):
    today = datetime.now().date()
    current_monday = today - timedelta(days=today.weekday())
    week_start = (current_monday + (timedelta(days=7) if today.weekday()==6 else timedelta(0))).isoformat()
    return templates.TemplateResponse("admin/schedule_timeslots.html", {"request": request, "week_start": week_start})
