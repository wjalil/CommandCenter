from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from calendar import month_name
from datetime import date

from app.db import get_db
from app.utils.tenant import get_current_tenant_id
from app.auth.dependencies import get_current_admin_user
from app.models.user import User
from app.models.catering import CateringMonthlyMenu, CateringProgram
from app.services.catering.weekly_ingredients import build_aggregate_ingredient_list

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
    })


@router.get(
    "/monthly-menus/{menu_id}",
    name="weekly_ingredient_list"
)
async def weekly_ingredient_list_redirect(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """
    Legacy per-menu ingredient link — redirects into the one shopping list,
    pre-filtered to that program and month, instead of maintaining a second view.
    """
    tenant_id = get_current_tenant_id(request)

    result = await db.execute(
        select(CateringMonthlyMenu)
        .where(
            CateringMonthlyMenu.id == menu_id,
            CateringMonthlyMenu.tenant_id == tenant_id,
        )
    )
    monthly_menu = result.scalar_one_or_none()

    if not monthly_menu:
        return RedirectResponse(url="/catering/monthly-menus", status_code=303)

    return RedirectResponse(
        url=f"/catering/weekly-ingredients/?year={monthly_menu.year}&month={monthly_menu.month}&program_id={monthly_menu.program_id}",
        status_code=303,
    )
