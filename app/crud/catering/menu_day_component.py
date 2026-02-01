from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import delete
from app.models.catering import CateringMenuDay
from app.models.catering.menu_day_component import MenuDayComponent
from app.schemas.catering.menu_day_component import (
    MenuDayComponentCreate,
    BulkMenuDayComponentUpdate,
    MenuDayComponentAssignment
)
import uuid
from datetime import date
from typing import List, Optional


async def create_menu_day_component(
    db: AsyncSession,
    menu_day_id: str,
    component: MenuDayComponentCreate
) -> MenuDayComponent:
    """Create a single menu day component"""
    new_component = MenuDayComponent(
        id=str(uuid.uuid4()),
        menu_day_id=menu_day_id,
        component_id=component.component_id,
        meal_slot=component.meal_slot.value,
        is_vegan=component.is_vegan,
        quantity=component.quantity,
        notes=component.notes
    )
    db.add(new_component)
    await db.commit()
    await db.refresh(new_component)
    return new_component


async def get_menu_day_components(
    db: AsyncSession,
    menu_day_id: str,
    meal_slot: Optional[str] = None
) -> List[MenuDayComponent]:
    """Get components for a menu day with eager loading of food_component and component_type"""
    from app.models.catering import FoodComponent

    query = (
        select(MenuDayComponent)
        .where(MenuDayComponent.menu_day_id == menu_day_id)
        .options(
            selectinload(MenuDayComponent.food_component).selectinload(FoodComponent.component_type)
        )
    )

    if meal_slot:
        query = query.where(MenuDayComponent.meal_slot == meal_slot)

    result = await db.execute(query)
    return result.scalars().all()


async def delete_menu_day_components(
    db: AsyncSession,
    menu_day_id: str,
    meal_slot: Optional[str] = None,
    commit: bool = False
) -> int:
    """Delete components from a menu day, optionally by meal_slot. Returns count deleted."""
    stmt = delete(MenuDayComponent).where(MenuDayComponent.menu_day_id == menu_day_id)

    if meal_slot:
        stmt = stmt.where(MenuDayComponent.meal_slot == meal_slot)

    result = await db.execute(stmt)
    if commit:
        await db.commit()
    return result.rowcount


async def get_or_create_menu_day(
    db: AsyncSession,
    monthly_menu_id: str,
    service_date: date
) -> CateringMenuDay:
    """Get existing menu day or create a new one"""
    result = await db.execute(
        select(CateringMenuDay).where(
            CateringMenuDay.monthly_menu_id == monthly_menu_id,
            CateringMenuDay.service_date == service_date
        )
    )
    menu_day = result.scalar_one_or_none()

    if not menu_day:
        menu_day = CateringMenuDay(
            id=str(uuid.uuid4()),
            monthly_menu_id=monthly_menu_id,
            service_date=service_date
        )
        db.add(menu_day)
        await db.flush()

    return menu_day


async def bulk_assign_components(
    db: AsyncSession,
    menu_day_id: str,
    components: List[MenuDayComponentAssignment],
    replace_existing: bool = True
) -> List[MenuDayComponent]:
    """
    Bulk assign components to a menu day.
    If replace_existing is True, deletes all existing components first.
    """
    if replace_existing:
        await delete_menu_day_components(db, menu_day_id)

    created_components = []
    for comp in components:
        new_component = MenuDayComponent(
            id=str(uuid.uuid4()),
            menu_day_id=menu_day_id,
            component_id=comp.component_id,
            meal_slot=comp.meal_slot.value,
            is_vegan=comp.is_vegan,
            quantity=comp.quantity,
            notes=comp.notes
        )
        db.add(new_component)
        created_components.append(new_component)

    await db.flush()
    return created_components


async def bulk_assign_components_to_days(
    db: AsyncSession,
    monthly_menu_id: str,
    menu_days_data: List[BulkMenuDayComponentUpdate]
) -> dict:
    """
    Bulk assign components across multiple days.
    Returns summary of operations.
    """
    total_components = 0
    days_updated = 0

    for day_data in menu_days_data:
        # Get or create the menu day
        menu_day = await get_or_create_menu_day(db, monthly_menu_id, day_data.service_date)

        # Assign components
        if day_data.components:
            await bulk_assign_components(
                db,
                menu_day.id,
                day_data.components,
                replace_existing=day_data.replace_existing
            )
            total_components += len(day_data.components)
            days_updated += 1
        elif day_data.replace_existing:
            # If no components and replace_existing, clear existing
            await delete_menu_day_components(db, menu_day.id)
            days_updated += 1

    await db.commit()

    return {
        "days_updated": days_updated,
        "components_assigned": total_components
    }
