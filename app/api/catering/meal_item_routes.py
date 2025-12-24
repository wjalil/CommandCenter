from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.schemas.catering import (
    CateringMealItemCreate,
    CateringMealItemUpdate,
    CateringMealItemRead
)
from app.crud.catering import meal_item
from app.db import get_db
from app.utils.tenant import get_current_tenant_id

router = APIRouter()


@router.post("/", response_model=CateringMealItemRead)
async def create_meal_item(
    request: Request,
    item: CateringMealItemCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new catering meal item"""
    tenant_id = get_current_tenant_id(request)
    item.tenant_id = tenant_id
    return await meal_item.create_meal_item(db, item)


@router.get("/", response_model=List[CateringMealItemRead])
async def list_meal_items(
    request: Request,
    meal_type: str = None,
    db: AsyncSession = Depends(get_db)
):
    """Get all meal items for the current tenant, optionally filtered by meal type"""
    tenant_id = get_current_tenant_id(request)
    return await meal_item.get_meal_items(db, tenant_id, meal_type)


@router.get("/{item_id}", response_model=CateringMealItemRead)
async def get_meal_item(
    request: Request,
    item_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific meal item"""
    tenant_id = get_current_tenant_id(request)
    item = await meal_item.get_meal_item(db, item_id, tenant_id)
    if not item:
        raise HTTPException(status_code=404, detail="Meal item not found")
    return item


@router.put("/{item_id}", response_model=CateringMealItemRead)
async def update_meal_item(
    request: Request,
    item_id: str,
    updates: CateringMealItemUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a meal item"""
    tenant_id = get_current_tenant_id(request)
    item = await meal_item.update_meal_item(db, item_id, tenant_id, updates)
    if not item:
        raise HTTPException(status_code=404, detail="Meal item not found")
    return item


@router.delete("/{item_id}")
async def delete_meal_item(
    request: Request,
    item_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a meal item"""
    tenant_id = get_current_tenant_id(request)
    item = await meal_item.delete_meal_item(db, item_id, tenant_id)
    if not item:
        raise HTTPException(status_code=404, detail="Meal item not found")
    return {"message": "Meal item deleted"}
