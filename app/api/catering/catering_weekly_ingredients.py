from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import date, datetime, timedelta
from calendar import monthrange
import uuid

from app.db import get_db
from app.utils.tenant import get_current_tenant_id
from app.auth.dependencies import get_current_admin_user
from app.models.user import User
from app.models.catering import CateringMonthlyMenu, CateringProgram
from app.models.catering.production_log import ProductionDailyLog
from app.services.catering.weekly_ingredients import build_range_ingredient_list

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Checked-off state for the shopping checklist is stored on the same
# ProductionDailyLog table the daily production sheet uses for its checkboxes
# (program_id=None, service_date reused as the selected range's start date,
# reference_key is the ingredient name) rather than a new table, since the
# shape is identical. A check is scoped to the exact range it was made on.
WEEKLY_SHOPPING_CHECK_TYPE = "weekly_shopping"


@router.get(
    "/",
    name="aggregate_ingredient_list"
)
async def aggregate_ingredient_list(
    request: Request,
    program_id: str = None,
    start_date: str = None,
    end_date: str = None,
    view: str = "category",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """
    Ingredient shopping list for a custom date range — defaults to the next
    3 days so it's short enough to actually order against, instead of a full
    week/month at once. Offers three groupings of the same data: by CACFP
    food-group category (the default, closest to shopping by aisle), by day,
    and by program.
    """
    tenant_id = get_current_tenant_id(request)
    today = date.today()

    try:
        range_start = date.fromisoformat(start_date) if start_date else today
    except ValueError:
        range_start = today
    try:
        range_end = date.fromisoformat(end_date) if end_date else range_start + timedelta(days=2)
    except ValueError:
        range_end = range_start + timedelta(days=2)
    if range_end < range_start:
        range_start, range_end = range_end, range_start

    if view not in ("category", "day", "program"):
        view = "category"

    # Get all programs for the filter dropdown
    result = await db.execute(
        select(CateringProgram)
        .where(CateringProgram.tenant_id == tenant_id, CateringProgram.is_active == True)
        .order_by(CateringProgram.name)
    )
    all_programs = result.scalars().all()

    data = await db.run_sync(
        lambda sync_db: build_range_ingredient_list(
            sync_db,
            tenant_id,
            range_start,
            range_end,
            program_id
        )
    )

    # Cross-reference persisted checked state so the checklist survives a refresh.
    # The check is per ingredient name within the range, so the same flag is
    # applied everywhere that ingredient shows up — Category, Day, and Program
    # views all share one checked state per ingredient.
    checked_names = set()
    if data["ingredients"]:
        logs_result = await db.execute(
            select(ProductionDailyLog.reference_key).where(
                ProductionDailyLog.tenant_id == tenant_id,
                ProductionDailyLog.check_type == WEEKLY_SHOPPING_CHECK_TYPE,
                ProductionDailyLog.service_date == range_start,
            )
        )
        checked_names = {row[0] for row in logs_result.all()}

    for ing in data["ingredients"]:
        ing["checked"] = ing["name"] in checked_names
    for day in data["by_day"]:
        for ing in day["ingredients"]:
            ing["checked"] = ing["name"] in checked_names
    for prog in data["by_program"]:
        for ing in prog["ingredients"]:
            ing["checked"] = ing["name"] in checked_names

    return templates.TemplateResponse("catering/weekly_ingredients.html", {
        "request": request,
        "by_category": data["by_category"],
        "by_day": data["by_day"],
        "by_program": data["by_program"],
        "programs_included": data["programs"],
        "total_ingredients": data["total_ingredients"],
        "all_programs": all_programs,
        "selected_program_id": program_id,
        "view": view,
        "range_start": range_start,
        "range_end": range_end,
        "today": today,
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
    pre-filtered to that program and spanning that menu's whole month,
    instead of maintaining a second view.
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

    month_start = date(monthly_menu.year, monthly_menu.month, 1)
    month_end = date(monthly_menu.year, monthly_menu.month, monthrange(monthly_menu.year, monthly_menu.month)[1])

    return RedirectResponse(
        url=f"/catering/weekly-ingredients/?start_date={month_start.isoformat()}&end_date={month_end.isoformat()}&program_id={monthly_menu.program_id}",
        status_code=303,
    )


@router.post("/toggle")
async def toggle_weekly_shopping_check(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """
    Toggle the "got it" checkbox for one ingredient on the shopping list.
    Body: {range_start: "YYYY-MM-DD", ingredient_name: str}
    Returns: {checked: bool}
    """
    tenant_id = get_current_tenant_id(request)
    body = await request.json()

    range_start_str = body.get("range_start") or body.get("week_start")
    ingredient_name = body.get("ingredient_name")
    if not range_start_str or not ingredient_name:
        return JSONResponse({"error": "range_start and ingredient_name required"}, status_code=400)

    try:
        range_start = date.fromisoformat(range_start_str)
    except ValueError:
        return JSONResponse({"error": "invalid range_start"}, status_code=400)

    result = await db.execute(
        select(ProductionDailyLog).where(
            ProductionDailyLog.tenant_id == tenant_id,
            ProductionDailyLog.service_date == range_start,
            ProductionDailyLog.check_type == WEEKLY_SHOPPING_CHECK_TYPE,
            ProductionDailyLog.reference_key == ingredient_name,
        )
    )
    # scalars().all() rather than scalar_one_or_none(): tolerate any
    # pre-existing duplicate rows instead of raising MultipleResultsFound.
    existing_rows = result.scalars().all()

    if existing_rows:
        for row in existing_rows:
            await db.delete(row)
        await db.commit()
        return JSONResponse({"checked": False})
    else:
        db.add(ProductionDailyLog(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            service_date=range_start,
            program_id=None,
            check_type=WEEKLY_SHOPPING_CHECK_TYPE,
            reference_key=ingredient_name,
            checked_by_user_id=user.id,
            checked_at=datetime.utcnow(),
        ))
        await db.commit()
        return JSONResponse({"checked": True})
