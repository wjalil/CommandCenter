from datetime import datetime, timedelta
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from uuid import uuid4
import logging

from app.models.timeclock import TimeEntry, TimeStatus
from app.models.user import User

log = logging.getLogger(__name__)


async def get_open_entry(db: AsyncSession, tenant_id: int, user_id: str):
    q = select(TimeEntry).where(
        and_(
            TimeEntry.tenant_id == tenant_id,
            TimeEntry.user_id == user_id,
            TimeEntry.status == TimeStatus.OPEN
        )
    )
    res = await db.execute(q)
    return res.scalars().first()


async def clock_in(db: AsyncSession, tenant_id: int, user_id: str, shift_id=None, ip=None, source=None):
    # Idempotent: if already OPEN, just return it
    open_entry = await get_open_entry(db, tenant_id, user_id)
    if open_entry:
        return open_entry

    e = TimeEntry(
        id=str(uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        shift_id=shift_id,
        clock_in=datetime.utcnow(),
        status=TimeStatus.OPEN,
        clock_in_ip=ip,
        clock_in_source=source or "web",
    )

    db.add(e)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await get_open_entry(db, tenant_id, user_id)
        if existing:
            log.info("clock_in idempotent hit: tenant=%s user=%s", tenant_id, user_id)
            return existing
        raise

    log.info("clock_in: tenant=%s user=%s entry=%s", tenant_id, user_id, e.id)
    return e


async def clock_out(db: AsyncSession, tenant_id: int, user_id: str, ip=None, source=None):
    e = await get_open_entry(db, tenant_id, user_id)
    if not e:
        log.warning("clock_out with no OPEN: tenant=%s user=%s", tenant_id, user_id)
        return None

    u = await db.get(User, user_id)
    rate = float(u.hourly_rate or 0)

    e.clock_out = datetime.utcnow()
    delta = e.clock_out - e.clock_in
    e.duration_minutes = max(0, int(delta.total_seconds() // 60))
    e.status = TimeStatus.CLOSED
    e.clock_out_ip = ip
    e.clock_out_source = source or "web"
    e.hourly_rate = rate
    e.gross_pay = round((e.duration_minutes / 60) * rate, 2)

    await db.flush()
    log.info(
        "clock_out: tenant=%s user=%s entry=%s minutes=%s gross=%s",
        tenant_id, user_id, e.id, e.duration_minutes, e.gross_pay,
    )
    return e


async def autoclose_stale_entries(db: AsyncSession, tenant_id: int, max_hours: int = 16):
    """Close any OPEN entries older than max_hours."""
    cutoff = datetime.utcnow() - timedelta(hours=max_hours)
    q = select(TimeEntry).where(
        and_(
            TimeEntry.tenant_id == tenant_id,
            TimeEntry.status == TimeStatus.OPEN,
            TimeEntry.clock_in < cutoff,
        )
    )
    res = await db.execute(q)
    entries = res.scalars().all()

    count = 0
    for e in entries:
        e.clock_out = datetime.utcnow()
        delta = e.clock_out - e.clock_in
        e.duration_minutes = max(0, int(delta.total_seconds() // 60))
        e.status = TimeStatus.CLOSED
        e.notes = (e.notes or "") + " | auto-closed (stale)"
        count += 1

    if count:
        await db.flush()
        log.warning("autoclosed %s stale OPEN entries for tenant=%s", count, tenant_id)
    return count
