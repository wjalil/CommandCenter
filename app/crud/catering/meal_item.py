from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.catering import CateringMealItem, CateringMealComponent
from app.schemas.catering import CateringMealItemCreate, CateringMealItemUpdate
import uuid


async def create_meal_item(db: AsyncSession, meal_item: CateringMealItemCreate):
    """Create a new catering meal item with components"""
    new_item = CateringMealItem(
        id=str(uuid.uuid4()),
        name=meal_item.name,
        description=meal_item.description,
        meal_type=meal_item.meal_type,
        is_vegan=meal_item.is_vegan,
        is_vegetarian=meal_item.is_vegetarian,
        photo_filename=meal_item.photo_filename,
        tenant_id=meal_item.tenant_id
    )
    db.add(new_item)
    await db.flush()

    # Add components
    for comp in meal_item.components:
        meal_component = CateringMealComponent(
            id=str(uuid.uuid4()),
            meal_item_id=new_item.id,
            food_component_id=comp.food_component_id,
            portion_oz=comp.portion_oz
        )
        db.add(meal_component)

    await db.commit()
    await db.refresh(new_item)
    return new_item


async def get_meal_items(db: AsyncSession, tenant_id: int, meal_type: str = None):
    """Get all meal items for a tenant, optionally filtered by meal type"""
    query = select(CateringMealItem).where(CateringMealItem.tenant_id == tenant_id)

    if meal_type:
        query = query.where(CateringMealItem.meal_type == meal_type)

    query = query.options(
        selectinload(CateringMealItem.components).selectinload(CateringMealComponent.food_component)
    ).order_by(CateringMealItem.name)

    result = await db.execute(query)
    return result.scalars().all()


async def get_meal_item(db: AsyncSession, item_id: str, tenant_id: int):
    """Get a specific meal item"""
    result = await db.execute(
        select(CateringMealItem)
        .where(CateringMealItem.id == item_id, CateringMealItem.tenant_id == tenant_id)
        .options(
            selectinload(CateringMealItem.components).selectinload(CateringMealComponent.food_component)
        )
    )
    return result.scalar_one_or_none()


async def update_meal_item(db: AsyncSession, item_id: str, tenant_id: int, updates: CateringMealItemUpdate):
    """Update a meal item"""
    item = await get_meal_item(db, item_id, tenant_id)
    if not item:
        return None

    update_data = updates.dict(exclude_unset=True, exclude={'components'})
    for key, value in update_data.items():
        setattr(item, key, value)

    # Update components if provided
    if updates.components is not None:
        # Delete existing components
        await db.execute(
            select(CateringMealComponent).where(CateringMealComponent.meal_item_id == item_id)
        )
        for comp in item.components:
            await db.delete(comp)

        # Add new components
        for comp in updates.components:
            meal_component = CateringMealComponent(
                id=str(uuid.uuid4()),
                meal_item_id=item.id,
                food_component_id=comp.food_component_id,
                portion_oz=comp.portion_oz
            )
            db.add(meal_component)

    await db.commit()
    await db.refresh(item)
    return item


async def update_meal_item_with_components(
    db: AsyncSession,
    item_id: str,
    tenant_id: int,
    name: str,
    description: str,
    meal_type: str,
    is_vegan: bool,
    is_vegetarian: bool,
    components: list
):
    """Update a meal item with new component data"""
    from app.schemas.catering import CateringMealItemUpdate

    updates = CateringMealItemUpdate(
        name=name,
        description=description,
        meal_type=meal_type,
        is_vegan=is_vegan,
        is_vegetarian=is_vegetarian,
        components=components
    )

    return await update_meal_item(db, item_id, tenant_id, updates)


async def delete_meal_item(db: AsyncSession, item_id: str, tenant_id: int):
    """Delete a meal item"""
    item = await get_meal_item(db, item_id, tenant_id)
    if item:
        await db.delete(item)
        await db.commit()
    return item
