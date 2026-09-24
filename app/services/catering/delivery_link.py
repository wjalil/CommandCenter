"""
Catering ↔ Delivery linkage.

Catering plans the day (which programs, which route, what order, what's in the
van); the delivery module runs it (drivers, pay, turn-by-turn, completion). The
two share records through three link columns rather than merged tables:

- DeliveryStop.catering_program_id — each catering program has exactly one
  delivery stop, created and kept in sync from the program here. The program is
  the source of truth for name/address/contact/active; the stop's notes stay
  delivery-owned (gate codes, dock instructions).
- DeliveryRouteTemplate.catering_route_code — the template whose weekday drivers
  and pay rates run a catering route (e.g. "R1").
- DeliveryRoute.catering_manifest_id — the daily route created from a released
  catering manifest.
"""
from datetime import date
from typing import Optional
import re

from sqlalchemy import delete as sa_delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.models.catering import CateringProgram, DailyManifest, DailyManifestStop
from app.models.delivery import (
    DeliveryStop, DeliveryRoute, DeliveryRouteStop,
    DeliveryRouteTemplate, DeliveryRouteTemplateDay,
)
import uuid


def parse_route_code(text: Optional[str]) -> tuple[Optional[str], Optional[int]]:
    """Split a route code into (route, stop order): 'R1' -> ('R1', None),
    legacy-style 'R1-4' -> ('R1', 4), blank -> (None, None). A non-numeric suffix
    ('BX-North') is kept whole as the route."""
    text = (text or "").strip()
    if not text:
        return None, None
    route, _, suffix = text.partition("-")
    if route.strip() and suffix.strip().isdigit():
        return route.strip(), int(suffix.strip())
    return text, None


def _stop_fields(program: CateringProgram) -> dict:
    return {
        "name": program.name,
        "address": program.address or None,
        "contact_name": program.client_name or None,
        "contact_phone": program.client_phone or None,
        "is_active": bool(program.is_active),
    }


def _apply(stop: DeliveryStop, fields: dict) -> bool:
    changed = False
    for key, value in fields.items():
        if getattr(stop, key) != value:
            setattr(stop, key, value)
            changed = True
    return changed


async def sync_program_delivery_stop(db: AsyncSession, program: CateringProgram) -> DeliveryStop:
    """Create or refresh the delivery stop mirroring this program. Flushes, doesn't commit."""
    result = await db.execute(select(DeliveryStop).where(DeliveryStop.catering_program_id == program.id))
    stop = result.scalar_one_or_none()
    if stop:
        _apply(stop, _stop_fields(program))
    else:
        stop = DeliveryStop(
            id=str(uuid.uuid4()),
            tenant_id=program.tenant_id,
            catering_program_id=program.id,
            **_stop_fields(program),
        )
        db.add(stop)
    await db.flush()
    return stop


async def ensure_program_delivery_stops(db: AsyncSession, tenant_id: int) -> int:
    """Backfill/refresh the delivery stop for every catering program of a tenant —
    creates missing ones and fixes any drift. Commits only if something changed.
    Returns how many stops were created."""
    programs = (await db.execute(
        select(CateringProgram).where(CateringProgram.tenant_id == tenant_id)
    )).scalars().all()
    if not programs:
        return 0
    stops = (await db.execute(
        select(DeliveryStop).where(
            DeliveryStop.tenant_id == tenant_id,
            DeliveryStop.catering_program_id.isnot(None),
        )
    )).scalars().all()
    stop_by_program = {s.catering_program_id: s for s in stops}

    created = 0
    changed = False
    for program in programs:
        stop = stop_by_program.get(program.id)
        if stop:
            changed |= _apply(stop, _stop_fields(program))
        else:
            db.add(DeliveryStop(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                catering_program_id=program.id,
                **_stop_fields(program),
            ))
            created += 1
    if created or changed:
        await db.commit()
    return created


async def catering_route_codes(db: AsyncSession, tenant_id: int) -> list[str]:
    """Every catering route an active program is on, naturally sorted (R2 before R10)."""
    codes = (await db.execute(
        select(CateringProgram.route_code).where(
            CateringProgram.tenant_id == tenant_id,
            CateringProgram.is_active == True,  # noqa: E712
            CateringProgram.route_code.isnot(None),
        )
    )).scalars().all()
    routes = {parse_route_code(code)[0] for code in codes if (code or "").strip()}
    return sorted(routes, key=lambda r: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", r)])


async def catering_route_templates(db: AsyncSession, tenant_id: int) -> dict[str, DeliveryRouteTemplate]:
    """{catering route code: its delivery template}, with weekday drivers loaded."""
    templates = (await db.execute(
        select(DeliveryRouteTemplate)
        .where(
            DeliveryRouteTemplate.tenant_id == tenant_id,
            DeliveryRouteTemplate.catering_route_code.isnot(None),
        )
        .options(
            selectinload(DeliveryRouteTemplate.template_days).selectinload(DeliveryRouteTemplateDay.driver),
            selectinload(DeliveryRouteTemplate.pay_rates),
        )
    )).scalars().all()
    return {t.catering_route_code: t for t in templates}


def template_day_for(template: Optional[DeliveryRouteTemplate], service_date: date) -> Optional[DeliveryRouteTemplateDay]:
    """The template's schedule row for this date's weekday, or None if it doesn't run that day."""
    if not template:
        return None
    return next((d for d in template.template_days if d.day_of_week == service_date.weekday()), None)


# ==================== DAILY ROUTE SYNC (manifest -> delivery route) ====================

def _route_stop_touched(rs: DeliveryRouteStop) -> bool:
    """A driver has already done something at this stop — never remove it."""
    return rs.status != "pending" or rs.arrival_time is not None or bool(rs.photo_filename)


async def delivery_route_for_manifest(db: AsyncSession, manifest_id: str) -> Optional[DeliveryRoute]:
    return (await db.execute(
        select(DeliveryRoute).where(DeliveryRoute.catering_manifest_id == manifest_id)
    )).scalar_one_or_none()


async def _create_route(db: AsyncSession, manifest: DailyManifest) -> DeliveryRoute:
    """New daily delivery route for a released manifest — driver and pay from the
    route's template for that weekday. No driver = an open route any driver can
    pick up (the delivery module's normal "available routes" flow)."""
    template = (await catering_route_templates(db, manifest.tenant_id)).get(manifest.route_code)
    template_day = template_day_for(template, manifest.service_date)
    driver_id = template_day.driver_id if template_day else None
    pay_rate = None
    if template and driver_id:
        pay_rate = next((pr.pay_rate for pr in template.pay_rates if pr.driver_id == driver_id), None)

    route = DeliveryRoute(
        id=str(uuid.uuid4()),
        name=template.name if template else manifest.route_code,
        date=manifest.service_date,
        assigned_driver_id=driver_id,
        status="assigned" if driver_id else "draft",
        template_id=template.id if template else None,
        driver_pay_rate=pay_rate,
        tenant_id=manifest.tenant_id,
        catering_manifest_id=manifest.id,
    )
    db.add(route)
    await db.flush()
    return route


async def sync_delivery_route_for_manifest(db: AsyncSession, manifest: DailyManifest) -> Optional[DeliveryRoute]:
    """Make the manifest's delivery route match it: one stop per program, in the
    manifest's (Route Board) order. Flushes, doesn't commit.

    - Creates the route on first sync once the manifest is released; before
      that (draft, never released) there's no driver-facing route.
    - A program no longer on the manifest is removed from the route — unless the
      driver already arrived/completed/skipped/photographed it, then it stays put.
    - Stops that aren't catering programs (added by hand in the delivery module,
      e.g. "pick up trays") keep their position; program stops fill the rest.
    - A completed route is history and is never changed.
    """
    route = await delivery_route_for_manifest(db, manifest.id)
    if route is None:
        if manifest.status != "released":
            return None
        route = await _create_route(db, manifest)
    if route.status == "completed":
        return route

    # Desired program stops, in driving order
    rows = (await db.execute(
        select(DailyManifestStop, CateringProgram)
        .join(CateringProgram, DailyManifestStop.program_id == CateringProgram.id)
        .where(DailyManifestStop.manifest_id == manifest.id)
    )).all()
    rows.sort(key=lambda r: (r[0].sort_order, r[1].name.lower()))
    desired = []
    for _, program in rows:
        desired.append((await sync_program_delivery_stop(db, program)).id)
    desired_set = set(desired)

    existing = (await db.execute(
        select(DeliveryRouteStop, DeliveryStop)
        .join(DeliveryStop, DeliveryRouteStop.stop_id == DeliveryStop.id)
        .where(DeliveryRouteStop.route_id == route.id)
        .order_by(DeliveryRouteStop.stop_order)
    )).all()

    # Current layout: fixed stops (manual extras, touched stops that left the
    # manifest) keep their slot; every other slot is filled by program stops in order
    by_stop_id = {}
    layout = []  # None = slot for the next program stop, else a fixed route stop
    for rs, dstop in existing:
        if dstop.id in desired_set:
            by_stop_id[dstop.id] = rs
            layout.append(None)
        elif dstop.catering_program_id and not _route_stop_touched(rs):
            await db.delete(rs)
        else:
            layout.append(rs)

    pending = iter(desired)

    def next_program_stop():
        stop_id = next(pending, None)
        if stop_id is None:
            return None
        rs = by_stop_id.get(stop_id)
        if rs is None:
            rs = DeliveryRouteStop(id=str(uuid.uuid4()), route_id=route.id, stop_id=stop_id, status="pending")
            db.add(rs)
        return rs

    final = []
    for slot in layout:
        rs = slot if slot is not None else next_program_stop()
        if rs is not None:
            final.append(rs)
    while (rs := next_program_stop()) is not None:
        final.append(rs)

    for order, rs in enumerate(final, start=1):
        rs.stop_order = order
    await db.flush()
    return route


async def sync_delivery_routes_from(db: AsyncSession, tenant_id: int, from_date: date) -> int:
    """Re-sync every catering delivery route dated from_date on (plus manifests
    released but not yet synced) — after Route Board / route-code changes that can
    move stops between manifests. Returns how many routes were synced."""
    has_route = select(DeliveryRoute.catering_manifest_id).where(DeliveryRoute.catering_manifest_id.isnot(None))
    manifests = (await db.execute(
        select(DailyManifest).where(
            DailyManifest.tenant_id == tenant_id,
            DailyManifest.service_date >= from_date,
            or_(DailyManifest.status == "released", DailyManifest.id.in_(has_route)),
        )
    )).scalars().all()
    synced = 0
    for manifest in manifests:
        if await sync_delivery_route_for_manifest(db, manifest):
            synced += 1
    return synced


async def retire_delivery_route_for_manifest(db: AsyncSession, manifest_id: str) -> None:
    """The manifest is about to be deleted: drop its delivery route if no driver
    has started it, otherwise keep the route as history and just unlink it."""
    route = await delivery_route_for_manifest(db, manifest_id)
    if not route:
        return
    stops = (await db.execute(
        select(DeliveryRouteStop).where(DeliveryRouteStop.route_id == route.id)
    )).scalars().all()
    if route.status in ("draft", "assigned") and not any(_route_stop_touched(rs) for rs in stops):
        await db.execute(sa_delete(DeliveryRouteStop).where(DeliveryRouteStop.route_id == route.id))
        await db.execute(sa_delete(DeliveryRoute).where(DeliveryRoute.id == route.id))
    else:
        route.catering_manifest_id = None
    await db.flush()
