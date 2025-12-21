from fastapi import APIRouter, Depends, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import pytz

from app.db import get_db
from app.models.shift import Shift
from app.models.task import Task, TaskTemplate
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.models.timeclock import TimeEntry, TimeStatus
from app.utils.timeclock_service import clock_in as svc_clock_in, clock_out as svc_clock_out
from app.models.customer.customer_order import CustomerOrder, OrderItem

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# -----------------------------
# Helpers
# -----------------------------
async def _load_worker_shifts(
    db: AsyncSession,
    worker_id: str,
    tenant_id: int
) -> List[Shift]:
    q = (
        select(Shift)
        .where(Shift.assigned_worker_id == worker_id)
        .where(Shift.tenant_id == tenant_id)
        .order_by(Shift.start_time)
        .options(
            selectinload(Shift.tasks)
                .selectinload(Task.template)
                .selectinload(TaskTemplate.items),
            selectinload(Shift.submissions),
        )
    )
    res = await db.execute(q)
    return res.scalars().all()


def _bucket_weekly(
    shifts: List[Shift]
) -> Tuple[Dict[str, List[Shift]], Dict[str, float], Dict[str, Dict[str, int]]]:
    """
    Returns:
      weekly_shifts: { "Month DD, YYYY": [Shift, ...], ... }
      weekly_hours:  { "Month DD, YYYY": hours_float, ... }
      shift_alerts:  { shift_id: {"pending": n, "total": m}, ... }
    """
    weekly_shifts: Dict[str, List[Shift]] = defaultdict(list)
    weekly_hours: Dict[str, float] = defaultdict(float)
    shift_alerts: Dict[str, Dict[str, int]] = {}

    for s in shifts:
        week_start = s.start_time - timedelta(days=s.start_time.weekday())
        week_label = week_start.strftime("%B %d, %Y")
        weekly_shifts[week_label].append(s)

        duration = (s.end_time - s.start_time).total_seconds() / 3600.0
        weekly_hours[week_label] += duration

        total_items = sum(len(t.template.items) for t in s.tasks if t.template)
        completed = len(s.submissions)
        pending = max(0, total_items - completed)
        shift_alerts[s.id] = {"pending": pending, "total": total_items}

    # convert defaultdicts to dicts for Jinja
    return dict(weekly_shifts), dict(weekly_hours), shift_alerts


# -----------------------------
# Worker: My Shifts (canonical)
# -----------------------------
@router.get("/worker/shifts")
async def worker_shift_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    # Only workers should see this page
    if getattr(user, "role", None) != "worker":
        return templates.TemplateResponse("unauthorized.html", {"request": request})

    shifts = await _load_worker_shifts(db, worker_id=user.id, tenant_id=user.tenant_id)
    weekly_shifts, weekly_hours, shift_alerts = _bucket_weekly(shifts)

    return templates.TemplateResponse(
        "worker_shifts.html",
        {
            "request": request,
            "weekly_shifts": weekly_shifts,
            "weekly_hours": weekly_hours,
            "worker_id": user.id,
            "worker_name": getattr(user, "name", "Worker"),
            "shift_alerts": shift_alerts,
            # expose to Jinja template
            "datetime": datetime,
            "timedelta": timedelta,
        },
    )


# -----------------------------
# Admin/Manager: View a worker's shifts
# (use if you need supervisors to open another user's schedule)
# -----------------------------
@router.get("/admin/workers/{worker_id}/shifts")
async def admin_view_worker_shifts(
    worker_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    # Only allow managers/admins; adjust roles as your app requires
    if getattr(user, "role", None) not in {"admin", "manager"}:
        return RedirectResponse(url="/", status_code=302)

    worker = await db.get(User, worker_id)
    if not worker or worker.tenant_id != user.tenant_id:
        return RedirectResponse(url="/", status_code=302)

    shifts = await _load_worker_shifts(db, worker_id=worker_id, tenant_id=user.tenant_id)
    weekly_shifts, weekly_hours, shift_alerts = _bucket_weekly(shifts)

    return templates.TemplateResponse(
        "worker_shifts.html",
        {
            "request": request,
            "weekly_shifts": weekly_shifts,
            "weekly_hours": weekly_hours,
            "worker_id": worker_id,
            "worker_name": getattr(worker, "name", "Worker"),
            "shift_alerts": shift_alerts,
            # expose to Jinja template
            "datetime": datetime,
            "timedelta": timedelta,
        },
    )


# -----------------------------
# Worker Home + Timeclock
# -----------------------------
@router.get("/worker/home")
async def worker_home(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    q = select(TimeEntry).where(
        and_(
            TimeEntry.tenant_id == user.tenant_id,
            TimeEntry.user_id == user.id,
            TimeEntry.status == TimeStatus.OPEN,
        )
    )
    res = await db.execute(q)
    open_entry = res.scalars().first()

    ctx = {
        "request": request,
        "worker_name": getattr(user, "name", "Worker"),
        "open_entry": open_entry,
        "pytz": pytz,
    }
    # keep your existing template pathing
    return templates.TemplateResponse("/worker_home.html", ctx)


@router.post("/worker/clock-in")
async def post_clock_in(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    shift_id: Optional[str] = Form(default=None),
):
    if shift_id is not None and not shift_id.strip():
        shift_id = None

    e = await svc_clock_in(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        shift_id=shift_id,
        ip=request.client.host if request.client else None,
        source="web",
    )
    await db.commit()
    return {"ok": True, "entry_id": e.id}


@router.post("/worker/clock-out")
async def post_clock_out(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    e = await svc_clock_out(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        ip=request.client.host if request.client else None,
        source="web",
    )
    await db.commit()
    return {"ok": True, "entry_id": e.id if e else None}


# View Orders as Workers
@router.get("/worker/orders")
async def worker_orders_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    # Only workers/staff should see this page
    if getattr(user, "role", None) not in {"worker", "admin", "manager"}:
        return templates.TemplateResponse("unauthorized.html", {"request": request})
    
    # Fetch orders for this tenant with related data
    result = await db.execute(
        select(CustomerOrder)
        .options(
            selectinload(CustomerOrder.customer),
            selectinload(CustomerOrder.items).selectinload(OrderItem.menu_item),
        )
        .where(CustomerOrder.tenant_id == user.tenant_id)
        .order_by(CustomerOrder.timestamp.desc())
    )
    orders = result.scalars().all()
    
    # Get filter parameter
    filter_param = request.query_params.get("filter", "ALL")
    
    return templates.TemplateResponse(
        "worker_order_view.html",
        {
            "request": request,
            "orders": orders,
            "worker_name": getattr(user, "name", "Worker"),
            "filter": filter_param,
        }
    )

#Toggle Order Status
@router.post("/worker/orders/{order_id}/update_status")
async def worker_update_order_status(
    order_id: str,
    status: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(CustomerOrder).where(
            CustomerOrder.id == order_id, 
            CustomerOrder.tenant_id == user.tenant_id
        )
    )
    order = result.scalar_one_or_none()

    if order:
        order.status = (status or "").strip()
        await db.commit()

    return RedirectResponse(url="/worker/orders?success=Order+updated", status_code=303)