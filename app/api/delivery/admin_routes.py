"""
Delivery Admin Routes

Admin endpoints for managing delivery stops and routes
"""
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing import Optional, List
from datetime import date, datetime, timedelta
from collections import OrderedDict
from calendar import monthcalendar, month_name as month_name_arr, setfirstweekday, SUNDAY
import json
import uuid

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.user import User
from app.models.delivery import DeliveryStop, DeliveryRoute, DeliveryRouteStop, DeliveryRouteTemplate
from app.services.catering.delivery_link import ensure_program_delivery_stops

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Stable palette used to color-code drivers on the routes calendar
ROUTE_CALENDAR_PALETTE = [
    "#4C6EF5", "#12B886", "#F59F00", "#E64980",
    "#7048E8", "#15AABF", "#FA5252", "#2F9E44",
]
UNASSIGNED_COLOR = "#94A3B8"


# ==================== DASHBOARD ====================

@router.get("/")
async def delivery_dashboard(
    request: Request,
    month: Optional[int] = None,
    year: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Delivery module dashboard: routes calendar, driver roster, and quick stats"""
    tenant_id = request.state.tenant_id
    today = date.today()
    month = month or today.month
    year = year or today.year

    # ---- Quick stats ----
    stops_result = await db.execute(
        select(DeliveryStop).where(
            DeliveryStop.tenant_id == tenant_id,
            DeliveryStop.is_active == True
        )
    )
    stops_count = len(stops_result.scalars().all())

    templates_result = await db.execute(
        select(DeliveryRouteTemplate).where(
            DeliveryRouteTemplate.tenant_id == tenant_id,
            DeliveryRouteTemplate.is_active == True,
        )
    )
    templates_count = len(templates_result.scalars().all())

    week_horizon_end = today + timedelta(days=7)
    unassigned_result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.date >= today,
            DeliveryRoute.date < week_horizon_end,
            DeliveryRoute.assigned_driver_id.is_(None),
        )
    )
    unassigned_count = len(unassigned_result.scalars().all())

    # ---- Routes for the displayed calendar month ----
    month_start = date(year, month, 1)
    month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    month_routes_result = await db.execute(
        select(DeliveryRoute)
        .where(
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.date >= month_start,
            DeliveryRoute.date < month_end,
        )
        .options(
            selectinload(DeliveryRoute.assigned_driver),
            selectinload(DeliveryRoute.route_stops),
        )
        .order_by(DeliveryRoute.date, DeliveryRoute.name)
    )
    month_routes = month_routes_result.scalars().all()

    routes_by_date: dict = {}
    for r in month_routes:
        routes_by_date.setdefault(r.date, []).append(r)

    driver_ids_seen = sorted({r.assigned_driver_id for r in month_routes if r.assigned_driver_id})
    driver_colors = {did: ROUTE_CALENDAR_PALETTE[i % len(ROUTE_CALENDAR_PALETTE)] for i, did in enumerate(driver_ids_seen)}
    driver_names = {r.assigned_driver_id: r.assigned_driver.name for r in month_routes if r.assigned_driver_id}

    routes_today = routes_by_date.get(today, [])
    routes_today_count = len(routes_today)
    active_drivers_today = len({r.assigned_driver_id for r in routes_today if r.assigned_driver_id})

    # ---- Calendar grid ----
    setfirstweekday(SUNDAY)
    month_weeks = monthcalendar(year, month)

    day_details = {}
    calendar_weeks = []
    for week in month_weeks:
        week_data = []
        for day_num in week:
            if day_num == 0:
                week_data.append({"day": "", "date": "", "in_month": False, "entries": []})
                continue

            date_obj = date(year, month, day_num)
            date_str = date_obj.isoformat()
            day_routes = routes_by_date.get(date_obj, [])

            entries = []
            for r in day_routes:
                color = driver_colors.get(r.assigned_driver_id, UNASSIGNED_COLOR)
                driver_name = r.assigned_driver.name if r.assigned_driver else "Unassigned"
                entries.append({
                    "route_id": r.id,
                    "route_name": r.name,
                    "driver_name": driver_name,
                    "color": color,
                    "status": r.status,
                    "unassigned": r.assigned_driver_id is None,
                })
                day_details[f"{date_str}|{r.id}"] = {
                    "route_name": r.name,
                    "driver_name": driver_name,
                    "color": color,
                    "date_label": f"{date_obj.strftime('%A, %B')} {date_obj.day}",
                    "status": r.status,
                    "stop_count": len(r.route_stops),
                }

            week_data.append({
                "day": day_num,
                "date": date_str,
                "in_month": True,
                "is_today": date_obj == today,
                "day_name": date_obj.strftime("%A"),
                "entries": entries,
            })
        calendar_weeks.append(week_data)

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    # ---- This week's driver roster (always the real current week, independent of the calendar month shown) ----
    current_monday = today - timedelta(days=today.weekday())
    current_sunday = current_monday + timedelta(days=6)

    if month_start <= current_monday and current_sunday < month_end:
        week_source = routes_by_date
    else:
        week_routes_result = await db.execute(
            select(DeliveryRoute)
            .where(
                DeliveryRoute.tenant_id == tenant_id,
                DeliveryRoute.date >= current_monday,
                DeliveryRoute.date <= current_sunday,
            )
            .options(selectinload(DeliveryRoute.assigned_driver))
            .order_by(DeliveryRoute.name)
        )
        week_source = {}
        for r in week_routes_result.scalars().all():
            week_source.setdefault(r.date, []).append(r)

    week_roster = []
    for i in range(7):
        d = current_monday + timedelta(days=i)
        day_routes = sorted(week_source.get(d, []), key=lambda r: r.name)
        week_roster.append({
            "date": d,
            "label": f"{d.strftime('%a, %b')} {d.day}",
            "is_today": d == today,
            "routes": [
                {
                    "id": r.id,
                    "name": r.name,
                    "driver_name": r.assigned_driver.name if r.assigned_driver else None,
                    "status": r.status,
                }
                for r in day_routes
            ],
        })

    return templates.TemplateResponse("delivery/dashboard.html", {
        "request": request,
        "stops_count": stops_count,
        "templates_count": templates_count,
        "routes_today_count": routes_today_count,
        "active_drivers_today": active_drivers_today,
        "unassigned_count": unassigned_count,
        "month": month,
        "year": year,
        "month_name": month_name_arr[month],
        "calendar_weeks": calendar_weeks,
        "day_details_json": json.dumps(day_details),
        "driver_colors": driver_colors,
        "driver_names": driver_names,
        "prev_month": prev_month,
        "prev_year": prev_year,
        "next_month": next_month,
        "next_year": next_year,
        "is_current_month": (month == today.month and year == today.year),
        "week_roster": week_roster,
    })


# ==================== STOPS ====================

@router.get("/stops")
async def stops_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """List all delivery stops"""
    tenant_id = request.state.tenant_id
    await ensure_program_delivery_stops(db, tenant_id)

    result = await db.execute(
        select(DeliveryStop)
        .where(DeliveryStop.tenant_id == tenant_id)
        .order_by(DeliveryStop.name)
    )
    stops = result.scalars().all()

    return templates.TemplateResponse("delivery/stops_list.html", {
        "request": request,
        "stops": stops,
    })


@router.post("/stops")
async def create_stop(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Create a new delivery stop"""
    tenant_id = request.state.tenant_id
    form = await request.form()

    stop = DeliveryStop(
        id=str(uuid.uuid4()),
        name=form.get("name"),
        address=form.get("address") or None,
        contact_name=form.get("contact_name") or None,
        contact_phone=form.get("contact_phone") or None,
        notes=form.get("notes") or None,
        is_active=True,
        tenant_id=tenant_id
    )
    db.add(stop)
    await db.commit()

    return RedirectResponse(url="/delivery/admin/stops", status_code=303)


@router.post("/stops/{stop_id}/edit")
async def update_stop(
    request: Request,
    stop_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Update a delivery stop"""
    tenant_id = request.state.tenant_id
    form = await request.form()

    result = await db.execute(
        select(DeliveryStop).where(
            DeliveryStop.id == stop_id,
            DeliveryStop.tenant_id == tenant_id
        )
    )
    stop = result.scalar_one_or_none()

    if stop:
        stop.notes = form.get("notes") or None
        # A catering program's stop takes name/address/contact/active from the
        # program (edit those on the program); only the notes are delivery's own.
        if not stop.catering_program_id:
            stop.name = form.get("name")
            stop.address = form.get("address") or None
            stop.contact_name = form.get("contact_name") or None
            stop.contact_phone = form.get("contact_phone") or None
            stop.is_active = "is_active" in form
        await db.commit()

    return RedirectResponse(url="/delivery/admin/stops", status_code=303)


@router.post("/stops/{stop_id}/delete")
async def delete_stop(
    request: Request,
    stop_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Soft delete a delivery stop"""
    tenant_id = request.state.tenant_id

    result = await db.execute(
        select(DeliveryStop).where(
            DeliveryStop.id == stop_id,
            DeliveryStop.tenant_id == tenant_id
        )
    )
    stop = result.scalar_one_or_none()

    if stop and not stop.catering_program_id:  # program stops follow the program's active flag
        stop.is_active = False
        await db.commit()

    return RedirectResponse(url="/delivery/admin/stops", status_code=303)


# ==================== ROUTES ====================

@router.get("/routes")
async def routes_list(
    request: Request,
    week_start: Optional[str] = None,   # ISO date — Monday that anchors the 4-week window
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """List delivery routes bucketed by week in a 4-week window."""
    tenant_id = request.state.tenant_id

    today = date.today()
    current_monday = today - timedelta(days=today.weekday())

    # Default window starts 1 week back so you see last week + this week + 2 upcoming
    if week_start:
        try:
            anchor = datetime.strptime(week_start, "%Y-%m-%d").date()
            # Snap to the Monday of whatever date was passed
            window_start = anchor - timedelta(days=anchor.weekday())
        except ValueError:
            window_start = current_monday - timedelta(weeks=1)
    else:
        window_start = current_monday - timedelta(weeks=1)

    window_end = window_start + timedelta(weeks=4)   # exclusive

    prev_window = (window_start - timedelta(weeks=4)).isoformat()
    next_window = (window_start + timedelta(weeks=4)).isoformat()

    query = (
        select(DeliveryRoute)
        .where(
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.date >= window_start,
            DeliveryRoute.date < window_end,
        )
        .options(
            selectinload(DeliveryRoute.assigned_driver),
            selectinload(DeliveryRoute.route_stops).selectinload(DeliveryRouteStop.stop),
        )
        .order_by(DeliveryRoute.date.desc())
    )

    result = await db.execute(query)
    routes = result.scalars().all()

    drivers_result = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            User.is_active == True
        ).order_by(User.name)
    )
    drivers = drivers_result.scalars().all()

    # Bucket into ordered dict keyed by week label (most recent first)
    weeks: dict = OrderedDict()
    for route in routes:
        monday = route.date - timedelta(days=route.date.weekday())
        sunday = monday + timedelta(days=6)
        key = monday.isoformat()
        if key not in weeks:
            label = f"{monday.strftime('%b %d')} – {sunday.strftime('%b %d, %Y')}"
            is_current = (monday == current_monday)
            is_future = (monday > current_monday)
            weeks[key] = {
                "label": label,
                "monday": monday,
                "is_current": is_current,
                "is_future": is_future,
                "routes": [],
            }
        weeks[key]["routes"].append(route)

    return templates.TemplateResponse("delivery/routes_list.html", {
        "request": request,
        "weeks": weeks,
        "drivers": drivers,
        "window_start": window_start,
        "window_end": window_end - timedelta(days=1),
        "prev_window": prev_window,
        "next_window": next_window,
        "is_default_window": (window_start == current_monday - timedelta(weeks=1)),
    })


@router.get("/routes/create")
async def route_create_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Show route creation form"""
    tenant_id = request.state.tenant_id

    # Get active stops
    stops_result = await db.execute(
        select(DeliveryStop).where(
            DeliveryStop.tenant_id == tenant_id,
            DeliveryStop.is_active == True
        ).order_by(DeliveryStop.name)
    )
    stops = stops_result.scalars().all()

    # Get drivers (workers and admins)
    drivers_result = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            User.is_active == True
        ).order_by(User.name)
    )
    drivers = drivers_result.scalars().all()

    return templates.TemplateResponse("delivery/route_edit.html", {
        "request": request,
        "route": None,
        "stops": stops,
        "drivers": drivers,
        "selected_stops": [],
    })


@router.post("/routes/create")
async def route_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Create a new delivery route"""
    tenant_id = request.state.tenant_id
    form = await request.form()

    # Parse date
    route_date = datetime.strptime(form.get("date"), "%Y-%m-%d").date()

    # Determine status based on driver assignment
    driver_id = form.get("assigned_driver_id") or None
    status = "assigned" if driver_id else "draft"

    pay_rate_raw = form.get("driver_pay_rate")
    driver_pay_rate = float(pay_rate_raw) if pay_rate_raw else None

    # Create route
    route = DeliveryRoute(
        id=str(uuid.uuid4()),
        name=form.get("name"),
        date=route_date,
        assigned_driver_id=driver_id,
        status=status,
        driver_pay_rate=driver_pay_rate,
        notes=form.get("notes") or None,
        tenant_id=tenant_id
    )
    db.add(route)
    await db.flush()

    # Add stops in order
    stop_ids = form.getlist("stop_ids[]")
    for order, stop_id in enumerate(stop_ids, start=1):
        if stop_id:
            route_stop = DeliveryRouteStop(
                id=str(uuid.uuid4()),
                route_id=route.id,
                stop_id=stop_id,
                stop_order=order,
                status="pending"
            )
            db.add(route_stop)

    await db.commit()

    return RedirectResponse(url="/delivery/admin/routes", status_code=303)


@router.get("/routes/{route_id}/edit")
async def route_edit_form(
    request: Request,
    route_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Show route edit form"""
    tenant_id = request.state.tenant_id

    # Get route with stops
    result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.id == route_id,
            DeliveryRoute.tenant_id == tenant_id
        ).options(
            selectinload(DeliveryRoute.route_stops).selectinload(DeliveryRouteStop.stop),
            selectinload(DeliveryRoute.assigned_driver)
        )
    )
    route = result.scalar_one_or_none()

    if not route:
        return RedirectResponse(url="/delivery/admin/routes", status_code=303)

    # Get all active stops
    stops_result = await db.execute(
        select(DeliveryStop).where(
            DeliveryStop.tenant_id == tenant_id,
            DeliveryStop.is_active == True
        ).order_by(DeliveryStop.name)
    )
    stops = stops_result.scalars().all()

    # Get drivers
    drivers_result = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            User.is_active == True
        ).order_by(User.name)
    )
    drivers = drivers_result.scalars().all()

    # Get selected stop IDs in order
    selected_stops = sorted(route.route_stops, key=lambda x: x.stop_order)

    return templates.TemplateResponse("delivery/route_edit.html", {
        "request": request,
        "route": route,
        "stops": stops,
        "drivers": drivers,
        "selected_stops": selected_stops,
    })


@router.post("/routes/{route_id}/edit")
async def route_update(
    request: Request,
    route_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Update a delivery route"""
    tenant_id = request.state.tenant_id
    form = await request.form()

    result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.id == route_id,
            DeliveryRoute.tenant_id == tenant_id
        ).options(
            selectinload(DeliveryRoute.route_stops)
        )
    )
    route = result.scalar_one_or_none()

    if not route:
        return RedirectResponse(url="/delivery/admin/routes", status_code=303)

    # Update basic info
    route.name = form.get("name")
    route.date = datetime.strptime(form.get("date"), "%Y-%m-%d").date()
    route.assigned_driver_id = form.get("assigned_driver_id") or None
    route.notes = form.get("notes") or None

    pay_rate_raw = form.get("driver_pay_rate")
    route.driver_pay_rate = float(pay_rate_raw) if pay_rate_raw else None

    # Update status based on driver assignment (only if still draft/assigned)
    if route.status in ["draft", "assigned"]:
        route.status = "assigned" if route.assigned_driver_id else "draft"

    # Remove existing stops and re-add
    for rs in route.route_stops:
        await db.delete(rs)

    # Add stops in order
    stop_ids = form.getlist("stop_ids[]")
    for order, stop_id in enumerate(stop_ids, start=1):
        if stop_id:
            route_stop = DeliveryRouteStop(
                id=str(uuid.uuid4()),
                route_id=route.id,
                stop_id=stop_id,
                stop_order=order,
                status="pending"
            )
            db.add(route_stop)

    await db.commit()

    return RedirectResponse(url="/delivery/admin/routes", status_code=303)


@router.post("/routes/{route_id}/assign")
async def route_assign_driver(
    request: Request,
    route_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Quick-assign (or unassign) a driver from the routes list"""
    tenant_id = request.state.tenant_id
    form = await request.form()

    result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.id == route_id,
            DeliveryRoute.tenant_id == tenant_id
        )
    )
    route = result.scalar_one_or_none()

    if route:
        route.assigned_driver_id = form.get("assigned_driver_id") or None
        if route.status in ["draft", "assigned"]:
            route.status = "assigned" if route.assigned_driver_id else "draft"
        await db.commit()

    week_start = form.get("week_start")
    redirect_url = f"/delivery/admin/routes?week_start={week_start}" if week_start else "/delivery/admin/routes"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/routes/{route_id}/delete")
async def route_delete(
    request: Request,
    route_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Delete a delivery route"""
    tenant_id = request.state.tenant_id

    result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.id == route_id,
            DeliveryRoute.tenant_id == tenant_id
        )
    )
    route = result.scalar_one_or_none()

    if route:
        await db.delete(route)
        await db.commit()

    return RedirectResponse(url="/delivery/admin/routes", status_code=303)


@router.post("/routes/{route_id}/duplicate")
async def route_duplicate(
    request: Request,
    route_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Duplicate a route to a new date"""
    tenant_id = request.state.tenant_id
    form = await request.form()

    # Get original route
    result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.id == route_id,
            DeliveryRoute.tenant_id == tenant_id
        ).options(
            selectinload(DeliveryRoute.route_stops)
        )
    )
    original = result.scalar_one_or_none()

    if not original:
        return RedirectResponse(url="/delivery/admin/routes", status_code=303)

    # Parse new date (defaults to tomorrow if not provided)
    new_date_str = form.get("new_date")
    if new_date_str:
        new_date = datetime.strptime(new_date_str, "%Y-%m-%d").date()
    else:
        new_date = date.today() + timedelta(days=1)

    # Create new route
    new_route = DeliveryRoute(
        id=str(uuid.uuid4()),
        name=original.name,
        date=new_date,
        assigned_driver_id=original.assigned_driver_id,
        status="assigned" if original.assigned_driver_id else "draft",
        notes=original.notes,
        tenant_id=tenant_id
    )
    db.add(new_route)
    await db.flush()

    # Copy stops
    for rs in sorted(original.route_stops, key=lambda x: x.stop_order):
        new_route_stop = DeliveryRouteStop(
            id=str(uuid.uuid4()),
            route_id=new_route.id,
            stop_id=rs.stop_id,
            stop_order=rs.stop_order,
            status="pending"
        )
        db.add(new_route_stop)

    await db.commit()

    return RedirectResponse(url=f"/delivery/admin/routes/{new_route.id}/edit", status_code=303)
