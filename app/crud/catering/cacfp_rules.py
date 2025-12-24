from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.catering import CACFPAgeGroup, CACFPComponentType, CACFPPortionRule


async def get_all_age_groups(db: AsyncSession):
    """Get all CACFP age groups"""
    result = await db.execute(
        select(CACFPAgeGroup).order_by(CACFPAgeGroup.sort_order)
    )
    return result.scalars().all()


async def get_all_component_types(db: AsyncSession):
    """Get all CACFP component types"""
    result = await db.execute(
        select(CACFPComponentType).order_by(CACFPComponentType.sort_order)
    )
    return result.scalars().all()


async def get_portion_rules(db: AsyncSession, age_group_id: int = None, meal_type: str = None):
    """Get CACFP portion rules, optionally filtered"""
    query = select(CACFPPortionRule)

    if age_group_id:
        query = query.where(CACFPPortionRule.age_group_id == age_group_id)
    if meal_type:
        query = query.where(CACFPPortionRule.meal_type == meal_type)

    result = await db.execute(query)
    return result.scalars().all()
