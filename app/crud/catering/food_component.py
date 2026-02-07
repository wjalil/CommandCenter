from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from app.models.catering import FoodComponent, CateringMealComponent, MenuDayComponent
from app.schemas.catering import FoodComponentCreate, FoodComponentUpdate


async def create_food_component(db: AsyncSession, component: FoodComponentCreate):
    """Create a new food component"""
    new_component = FoodComponent(
        name=component.name,
        component_type_id=component.component_type_id,
        default_portion_oz=component.default_portion_oz,
        is_vegan=component.is_vegan,
        is_vegetarian=component.is_vegetarian,
        tenant_id=component.tenant_id
    )
    db.add(new_component)
    await db.commit()
    await db.refresh(new_component)
    return new_component


async def get_food_components(db: AsyncSession, tenant_id: int):
    """Get all food components for a tenant"""
    result = await db.execute(
        select(FoodComponent)
        .where(FoodComponent.tenant_id == tenant_id)
        .options(selectinload(FoodComponent.component_type))
        .order_by(FoodComponent.name)
    )
    return result.scalars().all()


async def get_food_component(db: AsyncSession, component_id: int, tenant_id: int):
    """Get a specific food component"""
    result = await db.execute(
        select(FoodComponent)
        .where(FoodComponent.id == component_id, FoodComponent.tenant_id == tenant_id)
        .options(selectinload(FoodComponent.component_type))
    )
    return result.scalar_one_or_none()


async def update_food_component(db: AsyncSession, component_id: int, tenant_id: int, updates: FoodComponentUpdate):
    """Update a food component"""
    component = await get_food_component(db, component_id, tenant_id)
    if not component:
        return None

    # Support both Pydantic v1 (.dict()) and v2 (.model_dump())
    if hasattr(updates, 'model_dump'):
        update_data = updates.model_dump(exclude_unset=True)
    else:
        update_data = updates.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(component, key, value)

    await db.commit()
    # Re-fetch with relationship loaded for proper serialization
    return await get_food_component(db, component_id, tenant_id)


async def check_food_component_usage(db: AsyncSession, component_id: int):
    """Check if a food component is being used in meal items or menu days"""
    # Check CateringMealComponent usage
    meal_result = await db.execute(
        select(func.count()).where(CateringMealComponent.food_component_id == component_id)
    )
    meal_count = meal_result.scalar()

    # Check MenuDayComponent usage
    menu_result = await db.execute(
        select(func.count()).where(MenuDayComponent.component_id == component_id)
    )
    menu_count = menu_result.scalar()

    return meal_count, menu_count


async def delete_food_component(db: AsyncSession, component_id: int, tenant_id: int):
    """Delete a food component"""
    component = await get_food_component(db, component_id, tenant_id)
    if not component:
        return None, None

    # Check if component is in use
    meal_count, menu_count = await check_food_component_usage(db, component_id)
    if meal_count > 0 or menu_count > 0:
        return component, {"meal_items": meal_count, "menu_days": menu_count}

    await db.delete(component)
    await db.commit()
    return component, None
