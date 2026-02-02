from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from calendar import month_name
from datetime import date

from app.db import get_db
from app.utils.tenant import get_current_tenant_id
from app.auth.dependencies import get_current_admin_user
from app.models.user import User
from app.models.catering import CateringMonthlyMenu, CateringProgram
from app.services.catering.weekly_ingredients import build_weekly_ingredient_list, build_aggregate_ingredient_list

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get(
    "/",
    name="aggregate_ingredient_list"
)
async def aggregate_ingredient_list(
    request: Request,
    year: int = None,
    month: int = None,
    program_id: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """
    Aggregate weekly ingredient list across all programs for a month.
    This is the main shopping list view.
    """
    tenant_id = get_current_tenant_id(request)

    # Default to current month
    today = date.today()
    if not year:
        year = today.year
    if not month:
        month = today.month

    # Get all programs for the filter dropdown
    result = await db.execute(
        select(CateringProgram)
        .where(CateringProgram.tenant_id == tenant_id, CateringProgram.is_active == True)
        .order_by(CateringProgram.name)
    )
    all_programs = result.scalars().all()

    # Build aggregate ingredient list
    data = await db.run_sync(
        lambda sync_db: build_aggregate_ingredient_list(
            sync_db,
            tenant_id,
            year,
            month,
            program_id
        )
    )

    return templates.TemplateResponse("catering/weekly_ingredients.html", {
        "request": request,
        "year": year,
        "month": month,
        "month_name": month_name[month],
        "weeks": data["weeks"],
        "programs_included": data["programs"],
        "total_ingredients": data["total_ingredients"],
        "all_programs": all_programs,
        "selected_program_id": program_id,
        "is_aggregate": True,
    })


@router.get(
    "/monthly-menus/{menu_id}",
    name="weekly_ingredient_list"
)
async def weekly_ingredient_list(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """
    Weekly ingredient list for a specific monthly menu.
    """
    tenant_id = get_current_tenant_id(request)

    # Get monthly menu with program details
    result = await db.execute(
        select(CateringMonthlyMenu)
        .where(
            CateringMonthlyMenu.id == menu_id,
            CateringMonthlyMenu.tenant_id == tenant_id,
        )
        .options(selectinload(CateringMonthlyMenu.program))
    )
    monthly_menu = result.scalar_one_or_none()

    if not monthly_menu:
        return RedirectResponse(url="/catering/monthly-menus", status_code=303)

    # Build weekly ingredient list using sync session
    weeks = await db.run_sync(
        lambda sync_db: build_weekly_ingredient_list(
            sync_db,
            monthly_menu.id
        )
    )

    # Count total unique ingredients
    all_ingredients = set()
    for week in weeks:
        all_ingredients.update(week["ingredients"])

    return templates.TemplateResponse("catering/weekly_ingredients.html", {
        "request": request,
        "program": monthly_menu.program,
        "month": monthly_menu.month,
        "month_name": month_name[monthly_menu.month],
        "year": monthly_menu.year,
        "weeks": weeks,
        "menu_id": menu_id,
        "total_ingredients": len(all_ingredients),
        "is_aggregate": False,
    })
