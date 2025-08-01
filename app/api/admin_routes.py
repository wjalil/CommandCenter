from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload, joinedload
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict
import uuid, shutil, os

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.utils.admin import compute_weekly_shifts_and_hours
from app.models.shift import Shift
from app.models.task import Task, TaskTemplate
from app.models.user import User
from app.models.internal_task import InternalTask
from app.models.shortage_log import ShortageLog
from app.models.custom_modules.driver_order import DriverOrder
from app.models.custom_modules.vending_log import VendingLog
from app.models.custom_modules.machine import Machine
from app.core.constants import UPLOAD_PATHS
from app.schemas.shift import ShiftCreate
from app.crud import shift, internal_task

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = UPLOAD_PATHS['vending_logs']

# ------------------------- SHIFT ROUTES -------------------------

@router.get("/admin/shifts")
async def admin_shift_view(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_admin_user)):
    shifts = await shift.get_all_shifts(db, tenant_id=request.state.tenant_id)
    result = await db.execute(select(User).where(User.role == "worker"))
    workers = result.scalars().all()
    worker_names = {worker.id: worker.name for worker in workers}

    weekly_shifts, weekly_hours = compute_weekly_shifts_and_hours(shifts)

    result = await db.execute(select(TaskTemplate))
    task_templates = result.scalars().all()

    result = await db.execute(select(TaskTemplate.auto_assign_label).where(TaskTemplate.auto_assign_label != None))
    preset_labels = sorted(set(result.scalars().all()))

    for shift_list in weekly_shifts.values():
        shift_list.sort(key=lambda s: s.start_time)

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
async def delete_shift_html(shift_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_admin_user)):
    await shift.delete_shift(db, shift_id)
    return RedirectResponse(url="/admin/shifts", status_code=303)

@router.post("/shifts/{shift_id}/assign")
async def assign_shift_html(shift_id: str, user_id: str = Form(...), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_admin_user)):
    await shift.claim_shift(db, shift_id, user_id)
    return RedirectResponse(url="/admin/shifts", status_code=303)

@router.post("/admin/shifts/create")
async def create_shift_from_form(
    label: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    is_recurring: Optional[str] = Form(None),
    shift_type: str = Form(...),
    tenant_id: str = Form(...), 
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    shift_data = ShiftCreate(
        label=label,
        start_time=datetime.fromisoformat(start_time),
        end_time=datetime.fromisoformat(end_time),
        is_recurring=bool(is_recurring),
        shift_type=shift_type,
        tenant_id=tenant_id,
    )
    await shift.create_shift(db, shift_data, tenant_id)
    return RedirectResponse(url="/admin/shifts", status_code=303)

@router.post("/admin/shifts/generate_next_week")
async def generate_next_week(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_admin_user)):
    await shift.clone_next_week_recurring_shifts(db, tenant_id=user.tenant_id)
    return RedirectResponse(url="/admin/shifts", status_code=303)

# ------------------------- TASK ROUTES -------------------------

@router.post("/admin/assign-task/{shift_id}")
async def assign_task_to_shift(
    shift_id: str,
    task_type: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    if task_type.startswith("template_"):
        template_id = task_type.replace("template_", "")
        result = await db.execute(select(TaskTemplate).where(TaskTemplate.id == template_id))
        template = result.scalar_one_or_none()
        if template:
            db.add(Task(shift_id=shift_id, template_id=template.id))
            await db.commit()
    return RedirectResponse(url="/admin/shifts", status_code=303)

@router.post("/admin/remove_task")
async def remove_task_from_shift(request: Request, task_id: str = Form(...), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_admin_user)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task:
        await db.delete(task)
        await db.commit()
    return RedirectResponse(request.headers.get("referer", "/admin/shifts"), status_code=303)

# ------------------------- WORKER ROUTES -------------------------

@router.get("/admin/workers")
async def get_workers(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_admin_user)):
    result = await db.execute(select(User))
    workers = result.scalars().all()
    return templates.TemplateResponse("create_workers.html", {"request": request, "workers": workers})

@router.post("/admin/workers")
async def create_worker(
    name: str = Form(...),
    pin_code: str = Form(...),
    role: str = Form("worker"),
    worker_type: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    db.add(User(name=name, pin_code=pin_code, role=role, worker_type=worker_type,tenant_id=user.tenant_id))
    await db.commit()
    return RedirectResponse("/admin/workers", status_code=303)

@router.post("/admin/workers/delete/{user_id}")
async def delete_worker(user_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_admin_user)):
    result = await db.execute(select(User).where(User.id == user_id))
    worker = result.scalar_one_or_none()
    if worker:
        await db.delete(worker)
        await db.commit()
    return RedirectResponse(url="/admin/workers", status_code=302)

# ------------------------- ADMIN DASHBOARD -------------------------

@router.get("/admin/dashboard")
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_admin_user)):
    result = await db.execute(select(User).where(User.role == "worker"))
    workers = result.scalars().all()
    worker_names = {worker.id: worker.name for worker in workers}

    result = await db.execute(select(Shift))
    shifts = result.scalars().all()
    internal_tasks = await internal_task.get_all_tasks(db)
    _, weekly_hours = compute_weekly_shifts_and_hours(shifts)

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

# ------------------------- VENDING MACHINE ROUTES -------------------------

@router.get("/admin/machines")
async def show_add_machine_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    result = await db.execute(
        select(Machine).where(Machine.tenant_id == user.tenant_id)
    )
    machines = result.scalars().all()
    return templates.TemplateResponse(
        "custom_modules/add_machine.html",
        {"request": request, "machines": machines}
    )


@router.post("/admin/machines")
async def create_machine(
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    db.add(Machine(name=name, tenant_id=user.tenant_id))
    await db.commit()
    return RedirectResponse("/admin/machines", status_code=302)


@router.get("/admin/vending-logs")
async def view_vending_logs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    # ✅ Only logs from machines in this tenant
    result = await db.execute(
        select(VendingLog)
        .join(Machine)
        .where(Machine.tenant_id == user.tenant_id)
        .options(
            joinedload(VendingLog.submitter),
            joinedload(VendingLog.machine)
        )
        .order_by(VendingLog.timestamp.desc())
    )
    logs = result.scalars().all()

    # ✅ Only machines for this tenant
    machine_result = await db.execute(
        select(Machine).where(Machine.tenant_id == user.tenant_id)
    )
    machines = machine_result.scalars().all()

    grouped_logs = defaultdict(lambda: {"qr": [], "internal": []})
    for log in logs:
        machine_name = log.machine.name if log.machine else "Unknown Machine"
        source = (log.source or "internal").strip().lower()
        if source in grouped_logs[machine_name]:
            grouped_logs[machine_name][source].append(log)
        else:
            print(f"🚨 Unexpected source '{source}' for machine '{machine_name}'")

    return templates.TemplateResponse(
        "custom_modules/admin_vending_logs.html",
        {
            "request": request,
            "grouped_logs": grouped_logs,
            "machines": machines
        }
    )


@router.post("/admin/vending-logs")
async def admin_submit_vending_log(
    notes: str = Form(""),
    photos: list[UploadFile] = File(default=[]),
    machine_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    # ✅ Optional: You could validate here that machine_id belongs to current tenant
    photo_filenames = []
    for photo in photos:
        if photo.filename:
            ext = photo.filename.split(".")[-1]
            filename = f"{uuid.uuid4()}.{ext}"
            path = os.path.join(UPLOAD_DIR, filename)
            with open(path, "wb") as buffer:
                shutil.copyfileobj(photo.file, buffer)
            photo_filenames.append(filename)

    new_log = VendingLog(
        notes=notes,
        submitter_id=current_user.id,
        machine_id=machine_id,
        photo_filename=",".join(photo_filenames),
        issue_type="internal",
        source="internal"
    )
    db.add(new_log)
    await db.commit()
    return RedirectResponse("/admin/vending-logs", status_code=302)
