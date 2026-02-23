from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.catering import CateringMonthlyMenu, CateringMenuDay, MenuDayComponent, FoodComponent
from app.schemas.catering import MonthlyMenuCreate, MonthlyMenuUpdate, MenuDayAssignment
import uuid
from datetime import datetime


async def create_monthly_menu(db: AsyncSession, menu: MonthlyMenuCreate):
    """Create a new monthly menu"""
    new_menu = CateringMonthlyMenu(
        id=str(uuid.uuid4()),
        program_id=menu.program_id,
        month=menu.month,
        year=menu.year,
        menu_type=menu.menu_type,
        status="draft",
        tenant_id=menu.tenant_id
    )
    db.add(new_menu)
    await db.commit()
    await db.refresh(new_menu)
    return new_menu


async def get_monthly_menus(db: AsyncSession, tenant_id: int, program_id: str = None):
    """Get all monthly menus for a tenant"""
    query = select(CateringMonthlyMenu).where(CateringMonthlyMenu.tenant_id == tenant_id)

    if program_id:
        query = query.where(CateringMonthlyMenu.program_id == program_id)

    query = query.options(
        selectinload(CateringMonthlyMenu.menu_days),
        selectinload(CateringMonthlyMenu.program)
    ).order_by(CateringMonthlyMenu.year.desc(), CateringMonthlyMenu.month.desc())

    result = await db.execute(query)
    return result.scalars().all()


async def get_monthly_menu(db: AsyncSession, menu_id: str, tenant_id: int):
    """Get a specific monthly menu with all menu days"""
    result = await db.execute(
        select(CateringMonthlyMenu)
        .where(CateringMonthlyMenu.id == menu_id, CateringMonthlyMenu.tenant_id == tenant_id)
        .options(
            selectinload(CateringMonthlyMenu.menu_days).selectinload(CateringMenuDay.breakfast_item),
            selectinload(CateringMonthlyMenu.menu_days).selectinload(CateringMenuDay.lunch_item),
            selectinload(CateringMonthlyMenu.menu_days).selectinload(CateringMenuDay.snack_item),
            selectinload(CateringMonthlyMenu.menu_days).selectinload(CateringMenuDay.components).selectinload(MenuDayComponent.food_component).selectinload(FoodComponent.component_type),
            selectinload(CateringMonthlyMenu.program)
        )
    )
    return result.scalar_one_or_none()


async def update_monthly_menu(db: AsyncSession, menu_id: str, tenant_id: int, updates: MonthlyMenuUpdate):
    """Update a monthly menu (mainly status changes)"""
    menu = await get_monthly_menu(db, menu_id, tenant_id)
    if not menu:
        return None

    if updates.status:
        menu.status = updates.status
        if updates.status == "finalized":
            menu.finalized_at = datetime.utcnow()
        elif updates.status == "sent":
            menu.sent_at = datetime.utcnow()

    await db.commit()
    await db.refresh(menu)
    return menu


async def upsert_menu_day(db: AsyncSession, monthly_menu_id: str, menu_day: MenuDayAssignment):
    """Create or update a menu day"""
    # Check if menu day exists
    result = await db.execute(
        select(CateringMenuDay).where(
            CateringMenuDay.monthly_menu_id == monthly_menu_id,
            CateringMenuDay.service_date == menu_day.service_date
        )
    )
    existing_day = result.scalar_one_or_none()

    if existing_day:
        # Update existing
        existing_day.breakfast_item_id = menu_day.breakfast_item_id
        existing_day.breakfast_vegan_item_id = menu_day.breakfast_vegan_item_id
        existing_day.lunch_item_id = menu_day.lunch_item_id
        existing_day.lunch_vegan_item_id = menu_day.lunch_vegan_item_id
        existing_day.snack_item_id = menu_day.snack_item_id
        existing_day.snack_vegan_item_id = menu_day.snack_vegan_item_id
        existing_day.notes = menu_day.notes
        day = existing_day
    else:
        # Create new
        day = CateringMenuDay(
            id=str(uuid.uuid4()),
            monthly_menu_id=monthly_menu_id,
            service_date=menu_day.service_date,
            breakfast_item_id=menu_day.breakfast_item_id,
            breakfast_vegan_item_id=menu_day.breakfast_vegan_item_id,
            lunch_item_id=menu_day.lunch_item_id,
            lunch_vegan_item_id=menu_day.lunch_vegan_item_id,
            snack_item_id=menu_day.snack_item_id,
            snack_vegan_item_id=menu_day.snack_vegan_item_id,
            notes=menu_day.notes
        )
        db.add(day)

    await db.commit()
    await db.refresh(day)
    return day


async def bulk_update_menu_days(db: AsyncSession, monthly_menu_id: str, menu_days: list[MenuDayAssignment]):
    """Bulk update/create menu days"""
    results = []
    for menu_day in menu_days:
        day = await upsert_menu_day(db, monthly_menu_id, menu_day)
        results.append(day)
    return results


async def delete_monthly_menu(db: AsyncSession, menu_id: str, tenant_id: int):
    """Delete a monthly menu and all its menu days"""
    menu = await get_monthly_menu(db, menu_id, tenant_id)
    if menu:
        await db.delete(menu)
        await db.commit()
    return menu
