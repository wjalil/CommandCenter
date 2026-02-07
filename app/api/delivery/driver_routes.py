"""
Delivery Driver Routes

Driver-facing endpoints for viewing routes and tracking deliveries
"""
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing import Optional
from datetime import date, datetime
import uuid
import os

from app.db import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.models.delivery import DeliveryStop, DeliveryRoute, DeliveryRouteStop

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

    return templates.TemplateResponse("delivery/driver_routes.html", {
        "request": request,
        "todays_routes": todays_routes,
        "upcoming_routes": upcoming_routes,
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
            DeliveryRoute.assigned_driver_id == user.id
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

    return templates.TemplateResponse("delivery/driver_route_view.html", {
        "request": request,
        "route": route,
        "route_stops": sorted_stops,
        "completed_count": completed_count,
        "total_count": total_count,
    })


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
