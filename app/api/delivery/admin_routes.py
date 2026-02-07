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
import uuid

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.user import User
from app.models.delivery import DeliveryStop, DeliveryRoute, DeliveryRouteStop

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ==================== DASHBOARD ====================

@router.get("/")
async def delivery_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Delivery module dashboard"""
    tenant_id = request.state.tenant_id

    # Get counts
    stops_result = await db.execute(
        select(DeliveryStop).where(
            DeliveryStop.tenant_id == tenant_id,
            DeliveryStop.is_active == True
        )
    )
    stops_count = len(stops_result.scalars().all())

    today = date.today()
    routes_result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.date >= today
        )
    )
    routes_count = len(routes_result.scalars().all())

    return templates.TemplateResponse("delivery/dashboard.html", {
        "request": request,
        "stops_count": stops_count,
        "routes_count": routes_count,
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
        stop.name = form.get("name")
        stop.address = form.get("address") or None
        stop.contact_name = form.get("contact_name") or None
        stop.contact_phone = form.get("contact_phone") or None
        stop.notes = form.get("notes") or None
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

    if stop:
        stop.is_active = False
        await db.commit()

    return RedirectResponse(url="/delivery/admin/stops", status_code=303)


# ==================== ROUTES ====================

@router.get("/routes")
async def routes_list(
    request: Request,
    filter_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """List all delivery routes"""
    tenant_id = request.state.tenant_id

    query = select(DeliveryRoute).where(
        DeliveryRoute.tenant_id == tenant_id
    ).options(
        selectinload(DeliveryRoute.assigned_driver),
        selectinload(DeliveryRoute.route_stops).selectinload(DeliveryRouteStop.stop)
    ).order_by(DeliveryRoute.date.desc())

    if filter_date:
        try:
            parsed_date = datetime.strptime(filter_date, "%Y-%m-%d").date()
            query = query.where(DeliveryRoute.date == parsed_date)
        except ValueError:
            pass

    result = await db.execute(query)
    routes = result.scalars().all()

    return templates.TemplateResponse("delivery/routes_list.html", {
        "request": request,
        "routes": routes,
        "filter_date": filter_date or "",
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

    # Create route
    route = DeliveryRoute(
        id=str(uuid.uuid4()),
        name=form.get("name"),
        date=route_date,
        assigned_driver_id=driver_id,
        status=status,
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
