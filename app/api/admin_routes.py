from fastapi import APIRouter, Depends, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from typing import Optional
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.shift import Shift
from app.models.task import TaskTemplate,Task
from app.models.user import User
from app.db import get_db
from app.crud import shift
from app.schemas.shift import ShiftCreate
from collections import defaultdict
from datetime import timedelta
from app.auth.dependencies import get_current_admin_user
from app.models.custom_modules.driver import DriverOrder
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
from app.utils.admin import compute_weekly_shifts_and_hours
from app.models.internal_task import InternalTask
from app.crud import internal_task
from app.api.internal_task_routes import InternalTask
from app.models.shortage_log import ShortageLog

#---- Admin Shifts View
@router.get("/admin/shifts")
async def admin_shift_view(request: Request, db: AsyncSession = Depends(get_db)):
    shifts = await shift.get_all_shifts(db)
    result = await db.execute(select(User).where(User.role == "worker"))
    workers = result.scalars().all()
    worker_names = {worker.id: worker.name for worker in workers}

    weekly_shifts, weekly_hours = compute_weekly_shifts_and_hours(shifts)

    # ✅ Fetch all TaskTemplates to populate the dropdown
    result = await db.execute(select(TaskTemplate))
    task_templates = result.scalars().all()

    # Sort shifts by date within each week
    for shift_list in weekly_shifts.values():
        shift_list.sort(key=lambda s: s.start_time)

    # 🔁 Fetch all unique shift labels that are linked to templates
    result = await db.execute(
        select(TaskTemplate.auto_assign_label).where(TaskTemplate.auto_assign_label != None)
    )
    preset_labels = sorted(set(result.scalars().all()))

    print("🔍 Retrieved Shifts:")
    for s in shifts:
        print(f"{s.label} — {s.start_time} to {s.end_time}")

    return templates.TemplateResponse("admin_shift_list.html", {
        "request": request,
        "weekly_shifts": dict(weekly_shifts),
        "weekly_hours": dict(weekly_hours),
        "worker_names": worker_names,
        "workers": workers,
        "preset_labels": preset_labels,
        "task_templates": task_templates, 
    })

@router.post("/shifts/{shift_id}/delete")
async def delete_shift_html(shift_id: str, db: AsyncSession = Depends(get_db)):
    await shift.delete_shift(db, shift_id)
    return RedirectResponse(url="/admin/shifts", status_code=303)

@router.post("/shifts/{shift_id}/assign",response_class=RedirectResponse)
async def assign_shift_html(shift_id: str, user_id: str = Form(...), db: AsyncSession = Depends(get_db)):
    await shift.claim_shift(db, shift_id, user_id)
    return RedirectResponse(url="/admin/shifts", status_code=303)

@router.post("/admin/assign-task/{shift_id}")
async def assign_task_to_shift(
    shift_id: str,
    task_type: str = Form(...),
    db: AsyncSession = Depends(get_db),
):

    # 🧩 Standard Task
    if task_type.startswith("template_"):
        template_id = task_type.replace("template_", "")
        result = await db.execute(select(TaskTemplate).where(TaskTemplate.id == template_id))
        template = result.scalar_one_or_none()

        if not template:
            return RedirectResponse(url="/admin/shifts", status_code=404)

        new_task = Task(shift_id=shift_id, template_id=template.id)
        db.add(new_task)
        await db.commit()
        return RedirectResponse(url="/admin/shifts", status_code=303)

    # 🔧 Custom Driver Order
    elif task_type == "driver_order":
        result = await db.execute(select(DriverOrder).where(DriverOrder.shift_id == shift_id))
        existing = result.scalar_one_or_none()

        if not existing:
            custom = DriverOrder(shift_id=shift_id)
            db.add(custom)
            await db.commit()
        return RedirectResponse(url="/admin/shifts", status_code=303)

    # 🚫 Invalid
    return RedirectResponse(url="/admin/shifts", status_code=400)



@router.post("/admin/shifts/create",response_class=RedirectResponse)
async def create_shift_from_form(
    label: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    is_recurring: Optional[str] = Form(None),
    shift_type: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    shift_data = ShiftCreate(
        label=label,
        start_time=datetime.fromisoformat(start_time),
        end_time=datetime.fromisoformat(end_time),
        is_recurring=bool(is_recurring),
        shift_type=shift_type,
    )
    await shift.create_shift(db, shift_data)
    return RedirectResponse(url="/admin/shifts", status_code=303)

@router.post("/admin/shifts/generate_next_week")
async def generate_next_week(db: AsyncSession = Depends(get_db)):
    await shift.clone_next_week_recurring_shifts(db)
    return RedirectResponse(url="/admin/shifts", status_code=303)


# -- Admin: Create + View Workers
@router.get("/admin/workers",response_class=RedirectResponse)
async def get_workers(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User))
    workers = result.scalars().all()
    return templates.TemplateResponse("create_workers.html", {"request": request, "workers": workers})


@router.post("/admin/workers",include_in_schema=False, response_class=RedirectResponse)
async def create_worker(
    request: Request,
    name: str = Form(...),
    pin_code: str = Form(...),
    role: str = Form("worker"),  # default role
    worker_type: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    new_user = User(name=name, pin_code=pin_code, role=role,worker_type=worker_type)
    db.add(new_user)
    await db.commit()
    return RedirectResponse("/admin/workers", status_code=303)

#-- Delete Worker
@router.post("/admin/workers/delete/{user_id}",response_class=RedirectResponse)
async def delete_worker(user_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_admin_user)):
    result = await db.execute(select(User).where(User.id == user_id))
    worker = result.scalar_one_or_none()

    if not worker:
        return RedirectResponse(url="/admin/workers", status_code=302)

    await db.delete(worker)
    await db.commit()
    return RedirectResponse(url="/admin/workers", status_code=302)

#Admin Dashboard Views
@router.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_admin_user)):
    # Fetch workers
    result = await db.execute(select(User).where(User.role == "worker"))
    workers = result.scalars().all()
    worker_names = {worker.id: worker.name for worker in workers}

    # Fetch shifts
    result = await db.execute(select(Shift))
    shifts = result.scalars().all()

    # Fetch Internal Tasks
    internal_tasks = await internal_task.get_all_tasks(db)

    # Use shared utils function for weekly hours
    _, weekly_hours = compute_weekly_shifts_and_hours(shifts)

    # Fetch shortage logs
    result = await db.execute(select(ShortageLog).order_by(ShortageLog.timestamp.desc()))
    shortage_logs = result.scalars().all()
    unresolved_logs = [log for log in shortage_logs if not log.is_resolved]

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "user": user,
        "weekly_hours": weekly_hours,
        "worker_names": worker_names,
        "internal_tasks": internal_tasks,
        "shortage_logs": shortage_logs,
        "unresolved_logs": unresolved_logs,
    })

@router.get("/admin/shortages")
async def redirect_to_worker_shortages():
    return RedirectResponse(url="/shortage-form")