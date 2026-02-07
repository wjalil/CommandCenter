from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from collections import defaultdict
from datetime import datetime, timedelta, date as dt_date
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
from app.models.catering import CateringProgram, CateringMonthlyMenu

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


# -----------------------------
# Worker: View Program Menus
# -----------------------------
@router.get("/worker/menus")
async def worker_menus_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """List all program menus for workers to view"""
    if getattr(user, "role", None) not in {"worker", "admin", "manager"}:
        return templates.TemplateResponse("unauthorized.html", {"request": request})

    from calendar import month_name as cal_month_name

    # Get all monthly menus for this tenant, grouped by program
    result = await db.execute(
        select(CateringMonthlyMenu)
        .where(CateringMonthlyMenu.tenant_id == user.tenant_id)
        .options(
            selectinload(CateringMonthlyMenu.program),
            selectinload(CateringMonthlyMenu.menu_days),
        )
        .order_by(CateringMonthlyMenu.year.desc(), CateringMonthlyMenu.month.desc())
    )
    menus = result.scalars().all()

    # Add month_name attribute for display
    for menu in menus:
        menu.month_name = cal_month_name[menu.month]

    # Group by program
    programs_dict = defaultdict(list)
    for menu in menus:
        programs_dict[menu.program].append(menu)

    programs_with_menus = sorted(programs_dict.items(), key=lambda x: x[0].name)

    return templates.TemplateResponse("worker_menus.html", {
        "request": request,
        "programs_with_menus": programs_with_menus,
    })


@router.get("/worker/menus/{menu_id}/view")
async def worker_menu_view(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """View a menu (read-only share view) as a worker"""
    if getattr(user, "role", None) not in {"worker", "admin", "manager"}:
        return templates.TemplateResponse("unauthorized.html", {"request": request})

    from app.crud.catering import monthly_menu as menu_crud, program as program_crud
    from calendar import monthcalendar, month_name as cal_month_name, setfirstweekday, SUNDAY
    from datetime import date as dt_date
    import json

    monthly_menu = await menu_crud.get_monthly_menu(db, menu_id, user.tenant_id)
    if not monthly_menu:
        return RedirectResponse(url="/worker/menus", status_code=303)

    program = await program_crud.get_program(db, monthly_menu.program_id, user.tenant_id)
    if not program:
        return RedirectResponse(url="/worker/menus", status_code=303)

    service_days = json.loads(program.service_days) if isinstance(program.service_days, str) else (program.service_days or [])
    meal_types = json.loads(program.meal_types_required) if isinstance(program.meal_types_required, str) else (program.meal_types_required or [])

    setfirstweekday(SUNDAY)
    month_weeks = monthcalendar(monthly_menu.year, monthly_menu.month)
    menu_days_dict = {day.service_date.isoformat(): day for day in monthly_menu.menu_days}

    def get_component_preview(menu_day):
        preview = {'breakfast': '', 'lunch': '', 'snack': ''}
        if not menu_day or not hasattr(menu_day, 'components') or not menu_day.components:
            return preview
        for slot in ['breakfast', 'lunch', 'snack']:
            slot_components = sorted(
                [comp for comp in menu_day.components if comp.meal_slot == slot and not comp.is_vegan and comp.food_component],
                key=lambda c: c.sort_order if hasattr(c, 'sort_order') and c.sort_order else 0
            )
            names = [comp.food_component.name for comp in slot_components]
            preview[slot] = ', '.join(names)
        return preview

    calendar_weeks = []
    for week in month_weeks:
        week_data = []
        for day_num in week:
            if day_num == 0:
                week_data.append({
                    'day': '', 'date': '', 'in_month': False,
                    'is_service_day': False, 'menu_day': None,
                    'component_preview': {'breakfast': '', 'lunch': '', 'snack': ''}
                })
            else:
                date_obj = dt_date(monthly_menu.year, monthly_menu.month, day_num)
                date_str = date_obj.isoformat()
                day_name = date_obj.strftime('%A')
                is_service_day = day_name in service_days
                menu_day = menu_days_dict.get(date_str)
                week_data.append({
                    'day': day_num, 'date': date_str, 'in_month': True,
                    'is_service_day': is_service_day, 'menu_day': menu_day,
                    'component_preview': get_component_preview(menu_day)
                })
        calendar_weeks.append(week_data)

    generated_date = datetime.now().strftime('%B %d, %Y')
    show_sunday = 'Sunday' in service_days
    show_saturday = 'Saturday' in service_days

    return templates.TemplateResponse("catering/menu_share.html", {
        "request": request,
        "monthly_menu": monthly_menu,
        "program": program,
        "month_name": cal_month_name[monthly_menu.month],
        "year": monthly_menu.year,
        "service_days": service_days,
        "meal_types": meal_types,
        "calendar_weeks": calendar_weeks,
        "generated_date": generated_date,
        "show_sunday": show_sunday,
        "show_saturday": show_saturday,
        "worker_view": True,
    })


@router.get("/worker/menus/{menu_id}/pdf")
async def worker_menu_pdf(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Download menu as PDF for workers"""
    if getattr(user, "role", None) not in {"worker", "admin", "manager"}:
        return templates.TemplateResponse("unauthorized.html", {"request": request})

    from app.crud.catering import monthly_menu as menu_crud, program as program_crud
    from calendar import monthcalendar, month_name as cal_month_name, setfirstweekday, SUNDAY
    from datetime import date as dt_date
    from fastapi.responses import Response
    import json

    monthly_menu = await menu_crud.get_monthly_menu(db, menu_id, user.tenant_id)
    if not monthly_menu:
        return RedirectResponse(url="/worker/menus", status_code=303)

    program = await program_crud.get_program(db, monthly_menu.program_id, user.tenant_id)
    if not program:
        return RedirectResponse(url="/worker/menus", status_code=303)

    service_days = json.loads(program.service_days) if isinstance(program.service_days, str) else (program.service_days or [])
    meal_types = json.loads(program.meal_types_required) if isinstance(program.meal_types_required, str) else (program.meal_types_required or [])

    setfirstweekday(SUNDAY)
    month_weeks = monthcalendar(monthly_menu.year, monthly_menu.month)
    menu_days_dict = {day.service_date.isoformat(): day for day in monthly_menu.menu_days}

    def get_component_preview(menu_day):
        preview = {'breakfast': '', 'lunch': '', 'snack': ''}
        if not menu_day or not hasattr(menu_day, 'components') or not menu_day.components:
            return preview
        for slot in ['breakfast', 'lunch', 'snack']:
            slot_components = sorted(
                [comp for comp in menu_day.components if comp.meal_slot == slot and not comp.is_vegan and comp.food_component],
                key=lambda c: c.sort_order if hasattr(c, 'sort_order') and c.sort_order else 0
            )
            names = [comp.food_component.name for comp in slot_components]
            preview[slot] = ', '.join(names)
        return preview

    calendar_weeks = []
    for week in month_weeks:
        week_data = []
        for day_num in week:
            if day_num == 0:
                week_data.append({
                    'day': '', 'date': '', 'in_month': False,
                    'is_service_day': False, 'menu_day': None,
                    'component_preview': {'breakfast': '', 'lunch': '', 'snack': ''}
                })
            else:
                date_obj = dt_date(monthly_menu.year, monthly_menu.month, day_num)
                date_str = date_obj.isoformat()
                day_name = date_obj.strftime('%A')
                is_service_day = day_name in service_days
                menu_day = menu_days_dict.get(date_str)
                week_data.append({
                    'day': day_num, 'date': date_str, 'in_month': True,
                    'is_service_day': is_service_day, 'menu_day': menu_day,
                    'component_preview': get_component_preview(menu_day)
                })
        calendar_weeks.append(week_data)

    generated_date = datetime.now().strftime('%B %d, %Y')
    show_sunday = 'Sunday' in service_days
    show_saturday = 'Saturday' in service_days

    html_content = templates.TemplateResponse("catering/menu_share.html", {
        "request": request,
        "monthly_menu": monthly_menu,
        "program": program,
        "month_name": cal_month_name[monthly_menu.month],
        "year": monthly_menu.year,
        "service_days": service_days,
        "meal_types": meal_types,
        "calendar_weeks": calendar_weeks,
        "generated_date": generated_date,
        "show_sunday": show_sunday,
        "show_saturday": show_saturday,
        "worker_view": True,
    }).body.decode('utf-8')

    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html_content, base_url=str(request.base_url)).write_pdf()

        safe_name = program.name.replace(' ', '_')
        filename = f"{safe_name}_{cal_month_name[monthly_menu.month]}_{monthly_menu.year}_Menu.pdf"

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except ImportError:
        return RedirectResponse(
            url=f"/worker/menus/{menu_id}/view",
            status_code=303
        )


# -----------------------------
# Worker: Timeclock History
# -----------------------------
@router.get("/worker/timeclock")
async def worker_timeclock_history(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """View personal clock in/out history"""
    if getattr(user, "role", None) not in {"worker", "admin", "manager"}:
        return templates.TemplateResponse("unauthorized.html", {"request": request})

    # Default to current week (Monday to next Monday)
    today = dt_date.today()
    if not start:
        monday = today - timedelta(days=today.weekday())
        start = monday.isoformat()
    if not end:
        monday = today - timedelta(days=today.weekday())
        end_date = monday + timedelta(days=7)
        end = end_date.isoformat()

    s_date = datetime.fromisoformat(start).date() if isinstance(start, str) else start
    e_date = datetime.fromisoformat(end).date() if isinstance(end, str) else end

    # Fetch entries for this worker in the date range
    result = await db.execute(
        select(TimeEntry)
        .where(
            TimeEntry.tenant_id == user.tenant_id,
            TimeEntry.user_id == user.id,
            TimeEntry.clock_in >= s_date,
            TimeEntry.clock_in < e_date,
        )
        .order_by(TimeEntry.clock_in.desc())
    )
    entries = result.scalars().all()

    # Calculate totals
    total_minutes = sum(e.duration_minutes or 0 for e in entries)
    total_hours = round(total_minutes / 60, 2)
    total_gross = sum(float(e.gross_pay or 0) for e in entries)

    return templates.TemplateResponse("worker_timeclock.html", {
        "request": request,
        "entries": entries,
        "start": start,
        "end": end,
        "total_hours": total_hours,
        "total_gross": round(total_gross, 2),
        "worker_name": getattr(user, "name", "Worker"),
        "pytz": pytz,
    })