from fastapi import APIRouter, Depends, HTTPException, Request, Form
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
from fastapi.responses import RedirectResponse

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


@router.put("/{component_id}")
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
    return {"message": "Food component updated", "id": comp.id}


@router.delete("/{component_id}")
async def delete_food_component(
    request: Request,
    component_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete a food component"""
    tenant_id = get_current_tenant_id(request)
    comp, usage = await food_component.delete_food_component(db, component_id, tenant_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Food component not found")
    if usage:
        details = []
        if usage.get("meal_items", 0) > 0:
            details.append(f"{usage['meal_items']} meal item(s)")
        if usage.get("menu_days", 0) > 0:
            details.append(f"{usage['menu_days']} menu day(s)")
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete: component is used in {' and '.join(details)}"
        )
    return {"message": "Food component deleted"}


# NEW ROUTE: Form-based POST (for modal HTML)
# ----------------------
@router.post("/form")
async def create_food_component_form(
    request: Request,
    name: str = Form(...),
    component_type_id: int = Form(...),
    default_portion_oz: float = Form(...),
    is_vegan: bool = Form(False),
    is_vegetarian: bool = Form(False),
    db: AsyncSession = Depends(get_db)
):
    """
    Handle form submission from the modal.
    Safe: does not break existing JSON route.
    """
    tenant_id = get_current_tenant_id(request)
    component = FoodComponentCreate(
        name=name,
        component_type_id=component_type_id,
        default_portion_oz=default_portion_oz,
        is_vegan=is_vegan,
        is_vegetarian=is_vegetarian,
        tenant_id=tenant_id
    )
    await food_component.create_food_component(db, component)

    # redirect back to the list page after creation
    
    return RedirectResponse(url="/catering/food-components", status_code=303)