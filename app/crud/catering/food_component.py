from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.catering import FoodComponent
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

    update_data = updates.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(component, key, value)

    await db.commit()
    await db.refresh(component)
    return component


async def delete_food_component(db: AsyncSession, component_id: int, tenant_id: int):
    """Delete a food component"""
    component = await get_food_component(db, component_id, tenant_id)
    if component:
        await db.delete(component)
        await db.commit()
    return component
