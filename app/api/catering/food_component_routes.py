from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.schemas.catering import (
    FoodComponentCreate,
    FoodComponentUpdate,
    FoodComponentRead
)
from app.crud.catering import food_component
from app.db import get_db
from app.utils.tenant import get_current_tenant_id

router = APIRouter()


@router.post("/", response_model=FoodComponentRead)
async def create_food_component(
    request: Request,
    component: FoodComponentCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new food component"""
    tenant_id = get_current_tenant_id(request)
    component.tenant_id = tenant_id
    return await food_component.create_food_component(db, component)


@router.get("/", response_model=List[FoodComponentRead])
async def list_food_components(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get all food components for the current tenant"""
    tenant_id = get_current_tenant_id(request)
    return await food_component.get_food_components(db, tenant_id)


@router.get("/{component_id}", response_model=FoodComponentRead)
async def get_food_component(
    request: Request,
    component_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific food component"""
    tenant_id = get_current_tenant_id(request)
    comp = await food_component.get_food_component(db, component_id, tenant_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Food component not found")
    return comp


@router.put("/{component_id}", response_model=FoodComponentRead)
async def update_food_component(
    request: Request,
    component_id: int,
    updates: FoodComponentUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a food component"""
    tenant_id = get_current_tenant_id(request)
    comp = await food_component.update_food_component(db, component_id, tenant_id, updates)
    if not comp:
        raise HTTPException(status_code=404, detail="Food component not found")
    return comp


@router.delete("/{component_id}")
async def delete_food_component(
    request: Request,
    component_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete a food component"""
    tenant_id = get_current_tenant_id(request)
    comp = await food_component.delete_food_component(db, component_id, tenant_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Food component not found")
    return {"message": "Food component deleted"}
