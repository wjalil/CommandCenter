from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.schemas.catering import (
    MonthlyMenuCreate,
    MonthlyMenuUpdate,
    MonthlyMenuRead,
    MenuDayRead,
    BulkMenuDayUpdate,
    BulkComponentsRequest
)
from app.crud.catering import monthly_menu, menu_day_component
from app.db import get_db
from app.utils.tenant import get_current_tenant_id

router = APIRouter()


@router.post("/", response_model=MonthlyMenuRead)
async def create_monthly_menu(
    request: Request,
    menu: MonthlyMenuCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new monthly menu"""
    tenant_id = get_current_tenant_id(request)
    menu.tenant_id = tenant_id
    return await monthly_menu.create_monthly_menu(db, menu)


@router.get("/", response_model=List[MonthlyMenuRead])
async def list_monthly_menus(
    request: Request,
    program_id: str = None,
    db: AsyncSession = Depends(get_db)
):
    """Get all monthly menus for the current tenant"""
    tenant_id = get_current_tenant_id(request)
    return await monthly_menu.get_monthly_menus(db, tenant_id, program_id)


@router.get("/{menu_id}", response_model=MonthlyMenuRead)
async def get_monthly_menu(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific monthly menu"""
    tenant_id = get_current_tenant_id(request)
    menu = await monthly_menu.get_monthly_menu(db, menu_id, tenant_id)
    if not menu:
        raise HTTPException(status_code=404, detail="Monthly menu not found")
    return menu


@router.put("/{menu_id}", response_model=MonthlyMenuRead)
async def update_monthly_menu(
    request: Request,
    menu_id: str,
    updates: MonthlyMenuUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a monthly menu (e.g., change status to finalized)"""
    tenant_id = get_current_tenant_id(request)
    menu = await monthly_menu.update_monthly_menu(db, menu_id, tenant_id, updates)
    if not menu:
        raise HTTPException(status_code=404, detail="Monthly menu not found")
    return menu


@router.post("/{menu_id}/menu-days/bulk")
async def bulk_update_menu_days(
    request: Request,
    menu_id: str,
    menu_days_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """Bulk update/create menu days for a monthly menu"""
    tenant_id = get_current_tenant_id(request)

    # Verify the menu exists and belongs to tenant
    menu = await monthly_menu.get_monthly_menu(db, menu_id, tenant_id)
    if not menu:
        raise HTTPException(status_code=404, detail="Monthly menu not found")

    # Parse menu_days from request
    from app.schemas.catering import MenuDayAssignment
    menu_days = [MenuDayAssignment(**day) for day in menu_days_data.get("menu_days", [])]

    await monthly_menu.bulk_update_menu_days(db, menu_id, menu_days)

    # Return success message instead of trying to serialize the objects
    return {"success": True, "message": f"Updated {len(menu_days)} menu days"}


@router.delete("/{menu_id}")
async def delete_monthly_menu(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a monthly menu and all its menu days"""
    tenant_id = get_current_tenant_id(request)
    menu = await monthly_menu.delete_monthly_menu(db, menu_id, tenant_id)
    if not menu:
        raise HTTPException(status_code=404, detail="Monthly menu not found")
    return {"message": "Monthly menu deleted"}


@router.post("/{menu_id}/menu-days/components/bulk")
async def bulk_assign_components(
    request: Request,
    menu_id: str,
    data: BulkComponentsRequest,
    db: AsyncSession = Depends(get_db)
):
    """Bulk assign food components to multiple menu days"""
    tenant_id = get_current_tenant_id(request)

    # Verify the menu exists and belongs to tenant
    menu = await monthly_menu.get_monthly_menu(db, menu_id, tenant_id)
    if not menu:
        raise HTTPException(status_code=404, detail="Monthly menu not found")

    # Process bulk assignment
    result = await menu_day_component.bulk_assign_components_to_days(
        db, menu_id, data.menu_days
    )

    return {
        "success": True,
        "message": f"Assigned {result['components_assigned']} components across {result['days_updated']} days"
    }


@router.get("/{menu_id}/menu-days/{day_id}/components")
async def get_day_components(
    request: Request,
    menu_id: str,
    day_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get components for a specific menu day"""
    tenant_id = get_current_tenant_id(request)

    # Verify the menu exists and belongs to tenant
    menu = await monthly_menu.get_monthly_menu(db, menu_id, tenant_id)
    if not menu:
        raise HTTPException(status_code=404, detail="Monthly menu not found")

    components = await menu_day_component.get_menu_day_components(db, day_id)

    return [
        {
            "id": comp.id,
            "component_id": comp.component_id,
            "component_name": comp.food_component.name if comp.food_component else None,
            "component_type": comp.food_component.component_type.name if comp.food_component and comp.food_component.component_type else None,
            "meal_slot": comp.meal_slot,
            "is_vegan": comp.is_vegan,
            "quantity": float(comp.quantity) if comp.quantity else None,
            "notes": comp.notes
        }
        for comp in components
    ]
