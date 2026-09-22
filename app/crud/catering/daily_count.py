from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import date
import uuid

from app.models.catering import CateringDailyCount


async def get_counts_for_date(db: AsyncSession, tenant_id: int, service_date: date) -> dict:
    """All daily-count overrides for a tenant on one date, keyed by program_id -> {meal_slot: override}."""
    result = await db.execute(
        select(CateringDailyCount).where(
            CateringDailyCount.tenant_id == tenant_id,
            CateringDailyCount.service_date == service_date,
        )
    )
    overrides: dict = {}
    for c in result.scalars().all():
        overrides.setdefault(c.program_id, {})[c.meal_slot] = c
    return overrides


async def get_counts_for_program_date(db: AsyncSession, program_id: str, service_date: date) -> dict:
    """Daily-count overrides for a single program on one date, keyed by meal_slot."""
    result = await db.execute(
        select(CateringDailyCount).where(
            CateringDailyCount.program_id == program_id,
            CateringDailyCount.service_date == service_date,
        )
    )
    return {c.meal_slot: c for c in result.scalars().all()}


async def set_count(
    db: AsyncSession,
    tenant_id: int,
    program_id: str,
    service_date: date,
    meal_slot: str,
    count: int,
    vegan_count: int,
    user_id: str = None,
) -> CateringDailyCount:
    """Create or update the same-day override for one program+date+slot."""
    result = await db.execute(
        select(CateringDailyCount).where(
            CateringDailyCount.program_id == program_id,
            CateringDailyCount.service_date == service_date,
            CateringDailyCount.meal_slot == meal_slot,
        )
    )
    override = result.scalar_one_or_none()
    if override:
        override.count = count
        override.vegan_count = vegan_count
        override.updated_by_user_id = user_id
    else:
        override = CateringDailyCount(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            program_id=program_id,
            service_date=service_date,
            meal_slot=meal_slot,
            count=count,
            vegan_count=vegan_count,
            updated_by_user_id=user_id,
        )
        db.add(override)
    await db.commit()
    await db.refresh(override)
    return override
