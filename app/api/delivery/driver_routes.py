"""
Delivery Driver Routes

Driver-facing endpoints for viewing routes and tracking deliveries
"""
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing import Optional
from datetime import date, datetime
from collections import defaultdict
import calendar
import uuid
import os

from app.db import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.models.delivery import DeliveryStop, DeliveryRoute, DeliveryRouteStop
from app.models.catering import DailyManifestStop, DailyManifestItem
from app.utils.delivery_driver_helpers import next_driver_route, route_date_label, pending_maps_stops

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Upload directory for delivery photos
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "static", "uploads", "delivery")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ==================== MY ROUTES ====================

@router.get("/")
async def driver_routes_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """View my assigned routes (today and upcoming)"""
    tenant_id = request.state.tenant_id
    today = date.today()

    # Get routes assigned to this driver
    result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.assigned_driver_id == user.id,
            DeliveryRoute.date >= today
        ).options(
            selectinload(DeliveryRoute.route_stops).selectinload(DeliveryRouteStop.stop)
        ).order_by(DeliveryRoute.date)
    )
    routes = result.scalars().all()

    # Split into today's routes and upcoming
    todays_routes = [r for r in routes if r.date == today]
    upcoming_routes = [r for r in routes if r.date > today]

    # The route that should be front-and-center — today's if there is one,
    # otherwise the soonest upcoming route, so a driver checking tonight for
    # tomorrow's early route sees it immediately instead of "nothing today".
    next_route = next_driver_route(routes)
    next_route_label = route_date_label(next_route.date, today) if next_route else None
    next_route_is_today = bool(next_route and next_route.date == today)

    # Keep the spotlighted route from also appearing in the section below it
    today_display_routes = [r for r in todays_routes if not next_route or r.id != next_route.id]
    upcoming_display_routes = [r for r in upcoming_routes if not next_route or r.id != next_route.id]

    # Unassigned routes any driver can pick up
    available_result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.assigned_driver_id.is_(None),
            DeliveryRoute.date >= today
        ).options(
            selectinload(DeliveryRoute.route_stops).selectinload(DeliveryRouteStop.stop)
        ).order_by(DeliveryRoute.date)
    )
    available_routes = available_result.scalars().all()

    # Pending stops (with an address) per route, keyed by route id, for the
    # one-tap "Navigate" button on each route card.
    route_maps_stops = {r.id: pending_maps_stops(r) for r in routes}

    return templates.TemplateResponse("delivery/driver_routes.html", {
        "request": request,
        "todays_routes": todays_routes,
        "upcoming_routes": upcoming_routes,
        "today_display_routes": today_display_routes,
        "upcoming_display_routes": upcoming_display_routes,
        "available_routes": available_routes,
        "today": today,
        "next_route": next_route,
        "next_route_label": next_route_label,
        "next_route_is_today": next_route_is_today,
        "route_maps_stops": route_maps_stops,
    })


@router.get("/schedule")
async def driver_schedule(
    request: Request,
    month: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Calendar view of this driver's assigned routes, by month"""
    tenant_id = request.state.tenant_id
    today = date.today()

    if month:
        try:
            year, mon = (int(p) for p in month.split("-"))
            month_start = date(year, mon, 1)
        except (ValueError, TypeError):
            month_start = date(today.year, today.month, 1)
    else:
        month_start = date(today.year, today.month, 1)

    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    if month_start.month == 1:
        prev_month = date(month_start.year - 1, 12, 1)
    else:
        prev_month = date(month_start.year, month_start.month - 1, 1)

    result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.assigned_driver_id == user.id,
            DeliveryRoute.date >= month_start,
            DeliveryRoute.date < next_month,
        ).options(
            selectinload(DeliveryRoute.route_stops)
        ).order_by(DeliveryRoute.date)
    )
    routes = result.scalars().all()

    routes_by_day = defaultdict(list)
    for r in routes:
        routes_by_day[r.date.isoformat()].append(r)

    # Sunday-first month grid, padded with the trailing/leading days of
    # neighboring months so every week row has 7 days.
    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdatescalendar(month_start.year, month_start.month)

    return templates.TemplateResponse("delivery/driver_schedule.html", {
        "request": request,
        "month_start": month_start,
        "prev_month": prev_month,
        "next_month": next_month,
        "weeks": weeks,
        "routes_by_day": routes_by_day,
        "today": today,
    })


@router.get("/route/{route_id}")
async def driver_route_view(
    request: Request,
    route_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """View a specific route with all stops"""
    tenant_id = request.state.tenant_id

    result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.id == route_id,
            DeliveryRoute.tenant_id == tenant_id,
            or_(
                DeliveryRoute.assigned_driver_id == user.id,
                DeliveryRoute.assigned_driver_id.is_(None)
            )
        ).options(
            selectinload(DeliveryRoute.route_stops).selectinload(DeliveryRouteStop.stop)
        )
    )
    route = result.scalar_one_or_none()

    if not route:
        return RedirectResponse(url="/delivery/driver/", status_code=303)

    # Sort stops by order
    sorted_stops = sorted(route.route_stops, key=lambda x: x.stop_order)

    # Calculate progress
    completed_count = len([s for s in sorted_stops if s.status in ["completed", "skipped"]])
    total_count = len(sorted_stops)

    # Remaining stops with an address, in delivery order — fed to the
    # "Launch in Google Maps" button so the driver gets turn-by-turn nav
    # for everything left on the route (skips stops already done/skipped).
    maps_stops = [
        {"name": s.stop.name, "address": s.stop.address}
        for s in sorted_stops
        if s.status == "pending" and s.stop.address
    ]

    return templates.TemplateResponse("delivery/driver_route_view.html", {
        "request": request,
        "route": route,
        "route_stops": sorted_stops,
        "completed_count": completed_count,
        "total_count": total_count,
        "maps_stops": maps_stops,
        "manifest_by_route_stop": await _manifest_by_route_stop(db, route, sorted_stops),
    })


async def _manifest_by_route_stop(db: AsyncSession, route: DeliveryRoute, route_stops: list) -> dict:
    """For a route created from a catering manifest: {route stop id: {"items": [...],
    "instructions": str}} — what goes off the van at each stop, straight from the
    live manifest (so kitchen edits after release show up here too)."""
    if not route.catering_manifest_id:
        return {}
    manifest_stops = (await db.execute(
        select(DailyManifestStop)
        .where(DailyManifestStop.manifest_id == route.catering_manifest_id)
        .options(selectinload(DailyManifestStop.items))
    )).scalars().all()
    by_program = {ms.program_id: ms for ms in manifest_stops}
    result = {}
    for rs in route_stops:
        ms = by_program.get(rs.stop.catering_program_id) if rs.stop.catering_program_id else None
        if ms:
            result[rs.id] = {
                "items": sorted(ms.items, key=lambda i: i.sort_order),
                "instructions": ms.special_instructions,
            }
    return result


@router.post("/manifest-item/{item_id}/toggle")
async def toggle_manifest_item(
    request: Request,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Driver checks a manifest line off as delivered/unloaded at a stop. Only the
    driver assigned to the route carrying that manifest (or an admin) may toggle."""
    tenant_id = request.state.tenant_id
    row = (await db.execute(
        select(DailyManifestItem, DeliveryRoute)
        .join(DailyManifestStop, DailyManifestItem.stop_id == DailyManifestStop.id)
        .join(DeliveryRoute, DeliveryRoute.catering_manifest_id == DailyManifestStop.manifest_id)
        .where(DailyManifestItem.id == item_id, DeliveryRoute.tenant_id == tenant_id)
    )).first()
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    item, route = row
    if route.assigned_driver_id != user.id and user.role not in ("admin", "office_admin"):
        return JSONResponse({"error": "not your route"}, status_code=403)

    item.driver_confirmed = not item.driver_confirmed
    item.driver_confirmed_at = datetime.utcnow() if item.driver_confirmed else None
    item.driver_confirmed_by_user_id = user.id if item.driver_confirmed else None
    await db.commit()
    return JSONResponse({"confirmed": item.driver_confirmed})


# ==================== ROUTE ACTIONS ====================

@router.post("/route/{route_id}/start")
async def start_route(
    request: Request,
    route_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Mark route as in_progress"""
    tenant_id = request.state.tenant_id

    result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.id == route_id,
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.assigned_driver_id == user.id
        )
    )
    route = result.scalar_one_or_none()

    if route and route.status in ["draft", "assigned"]:
        route.status = "in_progress"
        await db.commit()

    return RedirectResponse(url=f"/delivery/driver/route/{route_id}", status_code=303)


@router.post("/route/{route_id}/complete")
async def complete_route(
    request: Request,
    route_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Mark route as completed"""
    tenant_id = request.state.tenant_id

    result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.id == route_id,
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.assigned_driver_id == user.id
        )
    )
    route = result.scalar_one_or_none()

    if route:
        route.status = "completed"
        await db.commit()

    return RedirectResponse(url="/delivery/driver/", status_code=303)


@router.post("/route/{route_id}/quick-complete")
async def quick_complete_route(
    request: Request,
    route_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Mark the route and every pending stop as completed in one action, skipping the per-stop flow"""
    tenant_id = request.state.tenant_id

    result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.id == route_id,
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.assigned_driver_id == user.id
        ).options(
            selectinload(DeliveryRoute.route_stops)
        )
    )
    route = result.scalar_one_or_none()

    if route and route.status in ["draft", "assigned", "in_progress"]:
        now = datetime.utcnow()
        for rs in route.route_stops:
            if rs.status == "pending":
                rs.status = "completed"
                rs.completed_at = now
                rs.departure_time = now
        route.status = "completed"
        await db.commit()

    return RedirectResponse(url="/delivery/driver/", status_code=303)


@router.post("/route/{route_id}/pickup")
async def pickup_route(
    request: Request,
    route_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Claim an unassigned route"""
    tenant_id = request.state.tenant_id

    result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.id == route_id,
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.assigned_driver_id.is_(None)
        )
    )
    route = result.scalar_one_or_none()

    if route:
        route.assigned_driver_id = user.id
        route.status = "assigned"
        await db.commit()

    return RedirectResponse(url=f"/delivery/driver/route/{route_id}", status_code=303)


@router.post("/route/{route_id}/drop")
async def drop_route(
    request: Request,
    route_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Release a claimed route back to the available pool (only before it's started)"""
    tenant_id = request.state.tenant_id

    result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.id == route_id,
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.assigned_driver_id == user.id
        )
    )
    route = result.scalar_one_or_none()

    if route and route.status == "assigned":
        route.assigned_driver_id = None
        route.status = "draft"
        await db.commit()

    return RedirectResponse(url="/delivery/driver/", status_code=303)


# ==================== STOP ACTIONS ====================

@router.post("/stop/{route_stop_id}/arrive")
async def arrive_at_stop(
    request: Request,
    route_stop_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Record arrival time at a stop"""
    tenant_id = request.state.tenant_id

    result = await db.execute(
        select(DeliveryRouteStop).where(
            DeliveryRouteStop.id == route_stop_id
        ).options(
            selectinload(DeliveryRouteStop.route)
        )
    )
    route_stop = result.scalar_one_or_none()

    if not route_stop:
        raise HTTPException(status_code=404, detail="Stop not found")

    # Verify ownership
    if route_stop.route.tenant_id != tenant_id or route_stop.route.assigned_driver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    route_stop.arrival_time = datetime.utcnow()
    await db.commit()

    return RedirectResponse(url=f"/delivery/driver/route/{route_stop.route_id}", status_code=303)


@router.post("/stop/{route_stop_id}/complete")
async def complete_stop(
    request: Request,
    route_stop_id: str,
    notes: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Mark stop as completed with optional notes and photo"""
    tenant_id = request.state.tenant_id

    result = await db.execute(
        select(DeliveryRouteStop).where(
            DeliveryRouteStop.id == route_stop_id
        ).options(
            selectinload(DeliveryRouteStop.route)
        )
    )
    route_stop = result.scalar_one_or_none()

    if not route_stop:
        raise HTTPException(status_code=404, detail="Stop not found")

    # Verify ownership
    if route_stop.route.tenant_id != tenant_id or route_stop.route.assigned_driver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Update stop
    route_stop.status = "completed"
    route_stop.completed_at = datetime.utcnow()
    route_stop.departure_time = datetime.utcnow()

    if notes:
        route_stop.notes = notes

    # Handle photo upload
    if photo and photo.filename:
        # Generate unique filename
        ext = os.path.splitext(photo.filename)[1]
        filename = f"{route_stop_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)

        # Save file
        content = await photo.read()
        with open(filepath, "wb") as f:
            f.write(content)

        route_stop.photo_filename = filename

    await db.commit()

    return RedirectResponse(url=f"/delivery/driver/route/{route_stop.route_id}", status_code=303)


@router.post("/stop/{route_stop_id}/skip")
async def skip_stop(
    request: Request,
    route_stop_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Skip a stop with reason"""
    tenant_id = request.state.tenant_id
    form = await request.form()

    result = await db.execute(
        select(DeliveryRouteStop).where(
            DeliveryRouteStop.id == route_stop_id
        ).options(
            selectinload(DeliveryRouteStop.route)
        )
    )
    route_stop = result.scalar_one_or_none()

    if not route_stop:
        raise HTTPException(status_code=404, detail="Stop not found")

    # Verify ownership
    if route_stop.route.tenant_id != tenant_id or route_stop.route.assigned_driver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    route_stop.status = "skipped"
    route_stop.completed_at = datetime.utcnow()
    route_stop.notes = form.get("reason") or "Skipped"

    await db.commit()

    return RedirectResponse(url=f"/delivery/driver/route/{route_stop.route_id}", status_code=303)
