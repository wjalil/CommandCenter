from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from calendar import month_name
from datetime import date, datetime
import uuid

from app.db import get_db
from app.utils.tenant import get_current_tenant_id
from app.auth.dependencies import get_current_admin_user
from app.models.user import User
from app.models.catering import CateringMonthlyMenu, CateringProgram
from app.models.catering.production_log import ProductionDailyLog
from app.services.catering.weekly_ingredients import build_aggregate_ingredient_list

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Checked-off state for the weekly shopping checklist is stored on the same
# ProductionDailyLog table the daily production sheet uses for its checkboxes
# (program_id=None, service_date reused as the week's Monday, reference_key
# is the ingredient name) rather than a new table, since the shape is identical.
WEEKLY_SHOPPING_CHECK_TYPE = "weekly_shopping"


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

    # Cross-reference persisted checked state so the checklist survives a refresh
    week_starts = [w["week_start"] for w in data["weeks"]]
    checked_set = set()
    if week_starts:
        logs_result = await db.execute(
            select(ProductionDailyLog.service_date, ProductionDailyLog.reference_key).where(
                ProductionDailyLog.tenant_id == tenant_id,
                ProductionDailyLog.check_type == WEEKLY_SHOPPING_CHECK_TYPE,
                ProductionDailyLog.service_date.in_(week_starts),
            )
        )
        checked_set = {(row[0], row[1]) for row in logs_result.all()}

    for week in data["weeks"]:
        for ing in week["ingredients"]:
            ing["checked"] = (week["week_start"], ing["name"]) in checked_set

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


@router.post("/toggle")
async def toggle_weekly_shopping_check(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """
    Toggle the "got it" checkbox for one ingredient on the weekly shopping list.
    Body: {week_start: "YYYY-MM-DD", ingredient_name: str}
    Returns: {checked: bool}
    """
    tenant_id = get_current_tenant_id(request)
    body = await request.json()

    week_start_str = body.get("week_start")
    ingredient_name = body.get("ingredient_name")
    if not week_start_str or not ingredient_name:
        return JSONResponse({"error": "week_start and ingredient_name required"}, status_code=400)

    try:
        week_start = date.fromisoformat(week_start_str)
    except ValueError:
        return JSONResponse({"error": "invalid week_start"}, status_code=400)

    result = await db.execute(
        select(ProductionDailyLog).where(
            ProductionDailyLog.tenant_id == tenant_id,
            ProductionDailyLog.service_date == week_start,
            ProductionDailyLog.check_type == WEEKLY_SHOPPING_CHECK_TYPE,
            ProductionDailyLog.reference_key == ingredient_name,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        await db.delete(existing)
        await db.commit()
        return JSONResponse({"checked": False})
    else:
        db.add(ProductionDailyLog(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            service_date=week_start,
            program_id=None,
            check_type=WEEKLY_SHOPPING_CHECK_TYPE,
            reference_key=ingredient_name,
            checked_by_user_id=user.id,
            checked_at=datetime.utcnow(),
        ))
        await db.commit()
        return JSONResponse({"checked": True})
