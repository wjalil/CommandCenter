"""
Catering Services API Routes

Exposes business logic services:
- Menu generation
- CACFP validation
- Invoice generation
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List
from datetime import date

from app.services.catering import (
    MenuGenerator,
    CACFPValidator,
    InvoiceGenerator,
    CACFPValidationError
)
from app.schemas.catering import (
    MonthlyMenuRead,
    CateringInvoiceRead
)
from app.db import get_db
from app.utils.tenant import get_current_tenant_id
from app.models.catering import CateringMealItem, CateringMenuDay, CateringProgram

router = APIRouter()


# ========== Menu Generation ==========

class GenerateMenuRequest(BaseModel):
    program_id: str
    month: int  # 1-12
    year: int
    variety_window: int = 5  # Days to avoid repeating meals


@router.post("/generate-menu", response_model=MonthlyMenuRead)
async def generate_monthly_menu(
    request: Request,
    req: GenerateMenuRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Auto-generate a monthly menu for a program.

    Creates a monthly menu with meal assignments for all service dates,
    automatically avoiding repeating the same meals too frequently.
    """
    tenant_id = get_current_tenant_id(request)

    # Verify program belongs to tenant
    program = await db.get(CateringProgram, req.program_id)
    if not program or program.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Program not found")

    generator = MenuGenerator(db)
    try:
        monthly_menu = await generator.generate_monthly_menu(
            program_id=req.program_id,
            month=req.month,
            year=req.year,
            variety_window=req.variety_window
        )
        return monthly_menu
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class RegenerateMenuDayRequest(BaseModel):
    meal_type: Optional[str] = None  # If specified, only regenerate this meal type


@router.post("/regenerate-menu-day/{menu_day_id}")
async def regenerate_menu_day(
    request: Request,
    menu_day_id: str,
    req: RegenerateMenuDayRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Regenerate meals for a specific menu day.

    Useful for getting new meal suggestions while keeping the rest of the menu intact.
    """
    tenant_id = get_current_tenant_id(request)

    # Verify menu day belongs to tenant
    menu_day = await db.get(CateringMenuDay, menu_day_id)
    if not menu_day:
        raise HTTPException(status_code=404, detail="Menu day not found")

    # Get monthly menu and verify tenant
    from app.models.catering import CateringMonthlyMenu
    monthly_menu = await db.get(CateringMonthlyMenu, menu_day.monthly_menu_id)
    if monthly_menu.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    generator = MenuGenerator(db)
    try:
        updated_menu_day = await generator.regenerate_menu_day(
            menu_day_id=menu_day_id,
            meal_type=req.meal_type
        )
        return {"message": "Menu day regenerated", "menu_day_id": updated_menu_day.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========== CACFP Validation ==========

@router.get("/validate-meal/{meal_item_id}")
async def validate_meal_item(
    request: Request,
    meal_item_id: str,
    age_group_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Validate a meal item against CACFP requirements for a specific age group.

    Returns detailed component analysis showing which requirements are met.
    """
    tenant_id = get_current_tenant_id(request)

    # Get meal item and verify tenant
    meal_item = await db.get(CateringMealItem, meal_item_id)
    if not meal_item or meal_item.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Meal item not found")

    validator = CACFPValidator(db)
    try:
        validation_result = await validator.validate_meal_item(meal_item, age_group_id)
        return validation_result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/validate-menu-day/{menu_day_id}")
async def validate_menu_day(
    request: Request,
    menu_day_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Validate all meals in a menu day against the program's CACFP requirements.

    Returns validation results for each meal type.
    """
    tenant_id = get_current_tenant_id(request)

    # Get menu day
    menu_day = await db.get(CateringMenuDay, menu_day_id)
    if not menu_day:
        raise HTTPException(status_code=404, detail="Menu day not found")

    # Get monthly menu and program
    from app.models.catering import CateringMonthlyMenu
    from sqlalchemy.future import select
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(CateringMonthlyMenu)
        .where(CateringMonthlyMenu.id == menu_day.monthly_menu_id)
        .options(selectinload(CateringMonthlyMenu.program))
    )
    monthly_menu = result.scalar_one_or_none()

    if not monthly_menu or monthly_menu.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    program = monthly_menu.program

    validator = CACFPValidator(db)
    try:
        validation_results = await validator.validate_menu_day(menu_day, program)
        return validation_results
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========== Invoice Generation ==========

class GenerateInvoiceRequest(BaseModel):
    program_id: str
    service_date: date
    regular_meal_count: Optional[int] = None
    vegan_meal_count: Optional[int] = None
    menu_day_id: Optional[str] = None
    monthly_menu_id: Optional[str] = None


@router.post("/generate-invoice", response_model=CateringInvoiceRead)
async def generate_invoice(
    request: Request,
    req: GenerateInvoiceRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Generate a single invoice for a service date.

    Meal counts default to the program's configured counts if not specified.
    """
    tenant_id = get_current_tenant_id(request)

    # Verify program belongs to tenant
    program = await db.get(CateringProgram, req.program_id)
    if not program or program.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Program not found")

    generator = InvoiceGenerator(db)
    try:
        invoice = await generator.generate_invoice_for_date(
            program_id=req.program_id,
            service_date=req.service_date,
            menu_day_id=req.menu_day_id,
            monthly_menu_id=req.monthly_menu_id,
            regular_meal_count=req.regular_meal_count,
            vegan_meal_count=req.vegan_meal_count
        )
        return invoice
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/generate-invoices-for-menu/{monthly_menu_id}", response_model=List[CateringInvoiceRead])
async def generate_invoices_for_menu(
    request: Request,
    monthly_menu_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Generate invoices for all service dates in a monthly menu.

    Creates one invoice per menu day with auto-generated invoice numbers.
    """
    tenant_id = get_current_tenant_id(request)

    # Verify monthly menu belongs to tenant
    from app.models.catering import CateringMonthlyMenu
    monthly_menu = await db.get(CateringMonthlyMenu, monthly_menu_id)
    if not monthly_menu or monthly_menu.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Monthly menu not found")

    generator = InvoiceGenerator(db)
    try:
        invoices = await generator.generate_invoices_for_month(monthly_menu_id)
        return invoices
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class CalculateInvoiceTotalRequest(BaseModel):
    regular_meal_count: int
    vegan_meal_count: int
    regular_price: float = 5.00
    vegan_price: float = 5.50


@router.post("/calculate-invoice-total")
async def calculate_invoice_total(req: CalculateInvoiceTotalRequest):
    """
    Calculate invoice totals for given meal counts and prices.

    Useful for previewing costs before generating invoices.
    """
    generator = InvoiceGenerator(None)  # No DB needed for calculation
    totals = generator.calculate_invoice_total(
        regular_meal_count=req.regular_meal_count,
        vegan_meal_count=req.vegan_meal_count,
        regular_price=req.regular_price,
        vegan_price=req.vegan_price
    )
    return totals
