"""
Delivery Route Templates

Admin endpoints for managing persistent route templates and generating daily routes.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import date, datetime, timedelta
import uuid

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.user import User
from app.models.delivery import (
    DeliveryStop, DeliveryRoute, DeliveryRouteStop,
    DeliveryRouteTemplate, DeliveryRouteTemplateStop, DeliveryRouteTemplateDay,
    DeliveryRoutePayRate,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _week_dates(for_date: date) -> list[date]:
    """Return Mon–Sun dates for the week containing for_date."""
    monday = for_date - timedelta(days=for_date.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


async def _get_drivers(db: AsyncSession, tenant_id: int) -> list[User]:
    result = await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.is_active == True).order_by(User.name)
    )
    return result.scalars().all()


async def _get_stops(db: AsyncSession, tenant_id: int) -> list[DeliveryStop]:
    result = await db.execute(
        select(DeliveryStop).where(
            DeliveryStop.tenant_id == tenant_id,
            DeliveryStop.is_active == True,
        ).order_by(DeliveryStop.name)
    )
    return result.scalars().all()


# ==================== LIST ====================

@router.get("/templates")
async def templates_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = request.state.tenant_id

    result = await db.execute(
        select(DeliveryRouteTemplate).where(
            DeliveryRouteTemplate.tenant_id == tenant_id,
        ).options(
            selectinload(DeliveryRouteTemplate.template_stops).selectinload(DeliveryRouteTemplateStop.stop),
            selectinload(DeliveryRouteTemplate.template_days).selectinload(DeliveryRouteTemplateDay.driver),
        ).order_by(DeliveryRouteTemplate.name)
    )
    route_templates = result.scalars().all()

    return templates.TemplateResponse("delivery/route_templates_list.html", {
        "request": request,
        "route_templates": route_templates,
        "day_names": DAY_NAMES,
    })


# ==================== CREATE ====================

@router.get("/templates/create")
async def template_create_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = request.state.tenant_id
    return templates.TemplateResponse("delivery/route_template_edit.html", {
        "request": request,
        "tmpl": None,
        "stops": await _get_stops(db, tenant_id),
        "drivers": await _get_drivers(db, tenant_id),
        "day_names": DAY_NAMES,
        "day_range": range(7),
        "selected_stops": [],
        "day_map": {},
        "pay_rate_map": {},
    })


@router.post("/templates/create")
async def template_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = request.state.tenant_id
    form = await request.form()

    tmpl = DeliveryRouteTemplate(
        id=str(uuid.uuid4()),
        name=form.get("name"),
        description=form.get("description") or None,
        is_active=True,
        tenant_id=tenant_id,
    )
    db.add(tmpl)
    await db.flush()

    # Stops (ordered list)
    for order, stop_id in enumerate(form.getlist("stop_ids[]"), start=1):
        if stop_id:
            db.add(DeliveryRouteTemplateStop(
                id=str(uuid.uuid4()),
                template_id=tmpl.id,
                stop_id=stop_id,
                stop_order=order,
            ))

    # Day assignments
    driver_ids_used = set()
    for dow in range(7):
        if form.get(f"day_{dow}_active"):
            driver_id = form.get(f"day_{dow}_driver_id") or None
            db.add(DeliveryRouteTemplateDay(
                id=str(uuid.uuid4()),
                template_id=tmpl.id,
                day_of_week=dow,
                driver_id=driver_id,
            ))
            if driver_id:
                driver_ids_used.add(driver_id)

    # Pay rates: pay_rate_{driver_id} for each driver used
    for driver_id in driver_ids_used:
        rate_str = form.get(f"pay_rate_{driver_id}") or ""
        if rate_str.strip():
            try:
                rate = float(rate_str)
                db.add(DeliveryRoutePayRate(
                    id=str(uuid.uuid4()),
                    template_id=tmpl.id,
                    driver_id=driver_id,
                    pay_rate=rate,
                ))
            except ValueError:
                pass

    await db.commit()
    return RedirectResponse(url="/delivery/admin/templates", status_code=303)


# ==================== EDIT ====================

@router.get("/templates/{template_id}/edit")
async def template_edit_form(
    request: Request,
    template_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = request.state.tenant_id

    result = await db.execute(
        select(DeliveryRouteTemplate).where(
            DeliveryRouteTemplate.id == template_id,
            DeliveryRouteTemplate.tenant_id == tenant_id,
        ).options(
            selectinload(DeliveryRouteTemplate.template_stops).selectinload(DeliveryRouteTemplateStop.stop),
            selectinload(DeliveryRouteTemplate.template_days).selectinload(DeliveryRouteTemplateDay.driver),
            selectinload(DeliveryRouteTemplate.pay_rates),
        )
    )
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        return RedirectResponse(url="/delivery/admin/templates", status_code=303)

    day_map = {d.day_of_week: d for d in tmpl.template_days}
    selected_stops = sorted(tmpl.template_stops, key=lambda s: s.stop_order)
    pay_rate_map = {pr.driver_id: float(pr.pay_rate) for pr in tmpl.pay_rates}

    return templates.TemplateResponse("delivery/route_template_edit.html", {
        "request": request,
        "tmpl": tmpl,
        "stops": await _get_stops(db, tenant_id),
        "drivers": await _get_drivers(db, tenant_id),
        "day_names": DAY_NAMES,
        "day_range": range(7),
        "selected_stops": selected_stops,
        "day_map": day_map,
        "pay_rate_map": pay_rate_map,
    })


@router.post("/templates/{template_id}/edit")
async def template_update(
    request: Request,
    template_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = request.state.tenant_id
    form = await request.form()

    result = await db.execute(
        select(DeliveryRouteTemplate).where(
            DeliveryRouteTemplate.id == template_id,
            DeliveryRouteTemplate.tenant_id == tenant_id,
        ).options(
            selectinload(DeliveryRouteTemplate.template_stops),
            selectinload(DeliveryRouteTemplate.template_days),
            selectinload(DeliveryRouteTemplate.pay_rates),
        )
    )
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        return RedirectResponse(url="/delivery/admin/templates", status_code=303)

    tmpl.name = form.get("name")
    tmpl.description = form.get("description") or None
    tmpl.is_active = "is_active" in form

    # Replace stops
    for ts in list(tmpl.template_stops):
        await db.delete(ts)
    await db.flush()
    for order, stop_id in enumerate(form.getlist("stop_ids[]"), start=1):
        if stop_id:
            db.add(DeliveryRouteTemplateStop(
                id=str(uuid.uuid4()),
                template_id=tmpl.id,
                stop_id=stop_id,
                stop_order=order,
            ))

    # Replace day assignments
    for td in list(tmpl.template_days):
        await db.delete(td)
    await db.flush()
    driver_ids_used = set()
    for dow in range(7):
        if form.get(f"day_{dow}_active"):
            driver_id = form.get(f"day_{dow}_driver_id") or None
            db.add(DeliveryRouteTemplateDay(
                id=str(uuid.uuid4()),
                template_id=tmpl.id,
                day_of_week=dow,
                driver_id=driver_id,
            ))
            if driver_id:
                driver_ids_used.add(driver_id)

    # Replace pay rates
    for pr in list(tmpl.pay_rates):
        await db.delete(pr)
    await db.flush()
    for driver_id in driver_ids_used:
        rate_str = form.get(f"pay_rate_{driver_id}") or ""
        if rate_str.strip():
            try:
                db.add(DeliveryRoutePayRate(
                    id=str(uuid.uuid4()),
                    template_id=tmpl.id,
                    driver_id=driver_id,
                    pay_rate=float(rate_str),
                ))
            except ValueError:
                pass

    await db.commit()
    return RedirectResponse(url="/delivery/admin/templates", status_code=303)


# ==================== DELETE ====================

@router.post("/templates/{template_id}/delete")
async def template_delete(
    request: Request,
    template_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = request.state.tenant_id

    result = await db.execute(
        select(DeliveryRouteTemplate).where(
            DeliveryRouteTemplate.id == template_id,
            DeliveryRouteTemplate.tenant_id == tenant_id,
        )
    )
    tmpl = result.scalar_one_or_none()
    if tmpl:
        await db.delete(tmpl)
        await db.commit()

    return RedirectResponse(url="/delivery/admin/templates", status_code=303)


# ==================== GENERATE ====================

@router.get("/routes/generate")
async def generate_form(
    request: Request,
    week_date: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = request.state.tenant_id

    # Default to current week
    try:
        anchor = datetime.strptime(week_date, "%Y-%m-%d").date() if week_date else date.today()
    except ValueError:
        anchor = date.today()

    week = _week_dates(anchor)
    week_start = week[0]
    week_end = week[6]

    # Load all active templates with stops + days
    result = await db.execute(
        select(DeliveryRouteTemplate).where(
            DeliveryRouteTemplate.tenant_id == tenant_id,
            DeliveryRouteTemplate.is_active == True,
        ).options(
            selectinload(DeliveryRouteTemplate.template_stops).selectinload(DeliveryRouteTemplateStop.stop),
            selectinload(DeliveryRouteTemplate.template_days).selectinload(DeliveryRouteTemplateDay.driver),
        ).order_by(DeliveryRouteTemplate.name)
    )
    route_templates = result.scalars().all()

    # Find which daily routes already exist for this week
    existing_result = await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.date >= week_start,
            DeliveryRoute.date <= week_end,
            DeliveryRoute.template_id != None,
        )
    )
    existing_routes = existing_result.scalars().all()
    # Key: (template_id, date) → route
    existing_map = {(r.template_id, r.date): r for r in existing_routes}

    # Build display structure: list of (template, [(date, template_day or None, already_exists)])
    schedule = []
    for tmpl in route_templates:
        day_map = {td.day_of_week: td for td in tmpl.template_days}
        days = []
        for d in week:
            td = day_map.get(d.weekday())
            already_exists = (tmpl.id, d) in existing_map
            days.append({
                "date": d,
                "template_day": td,
                "already_exists": already_exists,
                "existing_route": existing_map.get((tmpl.id, d)),
            })
        if any(item["template_day"] for item in days):
            schedule.append({"template": tmpl, "days": days})

    return templates.TemplateResponse("delivery/route_generate.html", {
        "request": request,
        "schedule": schedule,
        "week": week,
        "week_date": week_start.isoformat(),
        "prev_week": (week_start - timedelta(days=7)).isoformat(),
        "next_week": (week_start + timedelta(days=7)).isoformat(),
        "day_names": DAY_NAMES,
    })


@router.post("/routes/generate")
async def generate_routes(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = request.state.tenant_id
    form = await request.form()

    created = 0

    # Form encodes each slot as:
    #   generate_{template_id}_{date_iso} = "on"
    #   stops_{template_id}_{date_iso}[]  = [stop_id, ...]
    #
    # We collect all generate_ keys and process each.
    for key in form.keys():
        if not key.startswith("generate_"):
            continue

        _, template_id, date_iso = key.split("_", 2)

        # Load the template
        result = await db.execute(
            select(DeliveryRouteTemplate).where(
                DeliveryRouteTemplate.id == template_id,
                DeliveryRouteTemplate.tenant_id == tenant_id,
            ).options(
                selectinload(DeliveryRouteTemplate.template_days).selectinload(DeliveryRouteTemplateDay.driver),
                selectinload(DeliveryRouteTemplate.pay_rates),
            )
        )
        tmpl = result.scalar_one_or_none()
        if not tmpl:
            continue

        route_date = datetime.strptime(date_iso, "%Y-%m-%d").date()

        # Skip if a route from this template already exists for this date
        existing = await db.execute(
            select(DeliveryRoute).where(
                DeliveryRoute.template_id == template_id,
                DeliveryRoute.date == route_date,
                DeliveryRoute.tenant_id == tenant_id,
            )
        )
        if existing.scalar_one_or_none():
            continue

        # Get the day assignment for this weekday
        dow = route_date.weekday()
        day_map = {td.day_of_week: td for td in tmpl.template_days}
        template_day = day_map.get(dow)
        driver_id = template_day.driver_id if template_day else None

        # Look up stamped pay rate for this driver on this template
        pay_rate_map = {pr.driver_id: pr.pay_rate for pr in tmpl.pay_rates}
        driver_pay_rate = pay_rate_map.get(driver_id) if driver_id else None

        # Stops to include (submitted checkboxes)
        stop_ids = form.getlist(f"stops_{template_id}_{date_iso}[]")

        if not stop_ids:
            continue

        # Create the daily route
        route = DeliveryRoute(
            id=str(uuid.uuid4()),
            name=tmpl.name,
            date=route_date,
            assigned_driver_id=driver_id,
            status="assigned" if driver_id else "draft",
            template_id=template_id,
            driver_pay_rate=driver_pay_rate,
            tenant_id=tenant_id,
        )
        db.add(route)
        await db.flush()

        for order, stop_id in enumerate(stop_ids, start=1):
            db.add(DeliveryRouteStop(
                id=str(uuid.uuid4()),
                route_id=route.id,
                stop_id=stop_id,
                stop_order=order,
                status="pending",
            ))

        created += 1

    await db.commit()

    week_date = form.get("week_date", date.today().isoformat())
    return RedirectResponse(
        url=f"/delivery/admin/routes?created={created}",
        status_code=303,
    )
