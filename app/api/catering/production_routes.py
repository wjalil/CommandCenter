"""
Catering Production Routes

Daily production sheet for kitchen workers and admins.
Accessible to both admin and worker roles.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional
import json

from app.db import get_db
from app.auth.dependencies import get_current_admin_or_worker
from app.models.user import User
from app.models.catering import (
    CateringProgram,
    CateringMonthlyMenu,
    CateringMenuDay,
    CateringMealItem,
    CateringMealComponent,
    MenuDayComponent,
    ProductionDailyLog,
)
from app.models.catering.food_component import FoodComponent
from app.models.catering.cacfp_rules import CACFPComponentType
import uuid as _uuid

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

SUPPLY_TYPES = ["produce", "milk", "juice"]
SLOT_LABELS = {
    "breakfast": "B",
    "lunch": "L",
    "snack": "S",
    "am_snack": "AM",
    "pm_snack": "PM",
}


async def _build_production_data(db: AsyncSession, tenant_id: int, service_date: date):
    """
    Build aggregated production data for a given service date.
    Returns programs serving today, kitchen prep component list, checked states,
    and last supply delivery dates per program.
    """
    # Load all active programs with holidays
    programs_result = await db.execute(
        select(CateringProgram)
        .where(CateringProgram.tenant_id == tenant_id, CateringProgram.is_active == True)
        .options(selectinload(CateringProgram.holidays))
        .order_by(CateringProgram.name)
    )
    all_programs = programs_result.scalars().all()

    # Filter to programs serving on this date (service day + not a holiday)
    day_name = service_date.strftime("%A")
    serving_programs = []
    for program in all_programs:
        service_days = (
            json.loads(program.service_days)
            if isinstance(program.service_days, str)
            else (program.service_days or [])
        )
        if day_name not in service_days:
            continue
        holiday_dates = {h.holiday_date for h in program.holidays}
        if service_date in holiday_dates:
            continue
        serving_programs.append(program)

    # Load menu days for each serving program
    program_menu_days: dict[str, CateringMenuDay] = {}
    for program in serving_programs:
        result = await db.execute(
            select(CateringMonthlyMenu)
            .where(
                CateringMonthlyMenu.program_id == program.id,
                CateringMonthlyMenu.month == service_date.month,
                CateringMonthlyMenu.year == service_date.year,
                CateringMonthlyMenu.menu_type == "regular",
            )
            .options(
                selectinload(CateringMonthlyMenu.menu_days)
                    .selectinload(CateringMenuDay.components)
                    .selectinload(MenuDayComponent.food_component),
                selectinload(CateringMonthlyMenu.menu_days)
                    .selectinload(CateringMenuDay.breakfast_item)
                    .selectinload(CateringMealItem.components)
                    .selectinload(CateringMealComponent.food_component),
                selectinload(CateringMonthlyMenu.menu_days)
                    .selectinload(CateringMenuDay.breakfast_vegan_item)
                    .selectinload(CateringMealItem.components)
                    .selectinload(CateringMealComponent.food_component),
                selectinload(CateringMonthlyMenu.menu_days)
                    .selectinload(CateringMenuDay.lunch_item)
                    .selectinload(CateringMealItem.components)
                    .selectinload(CateringMealComponent.food_component),
                selectinload(CateringMonthlyMenu.menu_days)
                    .selectinload(CateringMenuDay.lunch_vegan_item)
                    .selectinload(CateringMealItem.components)
                    .selectinload(CateringMealComponent.food_component),
                selectinload(CateringMonthlyMenu.menu_days)
                    .selectinload(CateringMenuDay.snack_item)
                    .selectinload(CateringMealItem.components)
                    .selectinload(CateringMealComponent.food_component),
                selectinload(CateringMonthlyMenu.menu_days)
                    .selectinload(CateringMenuDay.am_snack_item)
                    .selectinload(CateringMealItem.components)
                    .selectinload(CateringMealComponent.food_component),
                selectinload(CateringMonthlyMenu.menu_days)
                    .selectinload(CateringMenuDay.pm_snack_item)
                    .selectinload(CateringMealItem.components)
                    .selectinload(CateringMealComponent.food_component),
            )
        )
        monthly_menu = result.scalar_one_or_none()
        if monthly_menu:
            menu_day = next(
                (d for d in monthly_menu.menu_days if d.service_date == service_date),
                None,
            )
            if menu_day:
                program_menu_days[program.id] = menu_day

    # Aggregate components across all programs
    # {component_name: {total_oz, slots (set), programs (list)}}
    component_agg: dict = defaultdict(lambda: {"total_oz": 0.0, "slots": set(), "programs": []})

    for program in serving_programs:
        menu_day = program_menu_days.get(program.id)
        if not menu_day:
            continue

        meal_types = (
            json.loads(program.meal_types_required)
            if isinstance(program.meal_types_required, str)
            else (program.meal_types_required or [])
        )
        meal_types_lower = [mt.lower().replace(" ", "_") for mt in meal_types]

        counts = {
            "breakfast": program.breakfast_count if program.breakfast_count is not None else program.total_children,
            "lunch": program.lunch_count if program.lunch_count is not None else program.total_children,
            "snack": program.snack_count if program.snack_count is not None else program.total_children,
            "am_snack": program.am_snack_count if program.am_snack_count is not None else program.total_children,
            "pm_snack": program.pm_snack_count if program.pm_snack_count is not None else program.total_children,
        }

        has_components = bool(menu_day.components)

        if has_components:
            for comp in menu_day.components:
                if comp.is_vegan or not comp.food_component:
                    continue
                slot = comp.meal_slot
                if slot not in meal_types_lower:
                    continue
                qty_oz = float(comp.quantity or comp.food_component.default_portion_oz or 0)
                meal_count = counts.get(slot, program.total_children) or 0
                name = comp.food_component.name
                component_agg[name]["total_oz"] += qty_oz * meal_count
                component_agg[name]["slots"].add(slot)
                if program.name not in component_agg[name]["programs"]:
                    component_agg[name]["programs"].append(program.name)
        else:
            slot_items = {
                "breakfast": menu_day.breakfast_item,
                "lunch": menu_day.lunch_item,
                "snack": menu_day.snack_item,
                "am_snack": menu_day.am_snack_item,
                "pm_snack": menu_day.pm_snack_item,
            }
            for slot, meal_item in slot_items.items():
                if slot not in meal_types_lower or not meal_item or not meal_item.components:
                    continue
                meal_count = counts.get(slot, program.total_children) or 0
                for mc in meal_item.components:
                    if not mc.food_component:
                        continue
                    name = mc.food_component.name
                    component_agg[name]["total_oz"] += float(mc.portion_oz or 0) * meal_count
                    component_agg[name]["slots"].add(slot)
                    if program.name not in component_agg[name]["programs"]:
                        component_agg[name]["programs"].append(program.name)

    # Sort components and convert sets to sorted label lists
    slot_order = list(SLOT_LABELS.keys())
    prep_components = []
    for name, data in sorted(component_agg.items()):
        slots_sorted = sorted(data["slots"], key=lambda s: slot_order.index(s) if s in slot_order else 99)
        prep_components.append({
            "name": name,
            "total_oz": round(data["total_oz"], 1),
            "slot_labels": [SLOT_LABELS.get(s, s) for s in slots_sorted],
            "programs": data["programs"],
        })

    # Load produce items: food components whose CACFP type contains "fruit"
    produce_result = await db.execute(
        select(FoodComponent.name)
        .join(FoodComponent.component_type)
        .where(
            FoodComponent.tenant_id == tenant_id,
            CACFPComponentType.name.ilike("%fruit%"),
        )
        .order_by(FoodComponent.name)
    )
    produce_items = [row[0] for row in produce_result.all()]

    # Load today's production logs
    logs_result = await db.execute(
        select(ProductionDailyLog).where(
            ProductionDailyLog.tenant_id == tenant_id,
            ProductionDailyLog.service_date == service_date,
        )
    )
    today_logs = logs_result.scalars().all()

    # checked_items: {(check_type, program_id_or_empty, reference_key_or_empty): log}
    checked_items: dict = {}
    for log in today_logs:
        key = (log.check_type, log.program_id or "", log.reference_key or "")
        checked_items[key] = log

    # Load last supply logs per program (most recent date before today for each supply type)
    last_supply: dict[str, dict] = {}
    last_supply_log: dict[str, dict] = {}
    for program in serving_programs:
        last_supply[program.id] = {}
        last_supply_log[program.id] = {}
        supply_result = await db.execute(
            select(ProductionDailyLog)
            .where(
                ProductionDailyLog.tenant_id == tenant_id,
                ProductionDailyLog.program_id == program.id,
                ProductionDailyLog.check_type.in_(SUPPLY_TYPES),
                ProductionDailyLog.service_date < service_date,
            )
            .order_by(ProductionDailyLog.service_date.desc())
        )
        for log in supply_result.scalars().all():
            if log.check_type not in last_supply[program.id]:
                last_supply[program.id][log.check_type] = log.service_date
                last_supply_log[program.id][log.check_type] = log

    # Build per-program delivery data for template
    programs_data = []
    for program in serving_programs:
        meal_types = (
            json.loads(program.meal_types_required)
            if isinstance(program.meal_types_required, str)
            else (program.meal_types_required or [])
        )
        meal_types_lower = [mt.lower().replace(" ", "_") for mt in meal_types]
        total_meals = max(
            [
                v
                for k, v in {
                    "breakfast": program.breakfast_count,
                    "lunch": program.lunch_count,
                    "snack": program.snack_count,
                    "am_snack": program.am_snack_count,
                    "pm_snack": program.pm_snack_count,
                }.items()
                if k in meal_types_lower and v is not None
            ],
            default=program.total_children or 0,
        )

        supply_checks = {}
        for supply in SUPPLY_TYPES:
            if supply == "produce":
                # Produce logs match any reference_key (items JSON stored there)
                produce_log = next(
                    (log for log in today_logs
                     if log.check_type == "produce" and log.program_id == program.id),
                    None,
                )
                selected_items = []
                if produce_log and produce_log.reference_key:
                    try:
                        selected_items = json.loads(produce_log.reference_key)
                    except (ValueError, TypeError):
                        selected_items = []
                last_produce_log = last_supply_log[program.id].get("produce")
                last_items = []
                if last_produce_log and last_produce_log.reference_key:
                    try:
                        last_items = json.loads(last_produce_log.reference_key)
                    except (ValueError, TypeError):
                        last_items = []
                supply_checks[supply] = {
                    "checked": produce_log is not None,
                    "checked_at": produce_log.checked_at if produce_log else None,
                    "last_date": last_supply[program.id].get(supply),
                    "selected_items": selected_items,
                    "last_items": last_items,
                }
            else:
                key = (supply, program.id, "")
                log = checked_items.get(key)
                supply_checks[supply] = {
                    "checked": log is not None,
                    "checked_at": log.checked_at if log else None,
                    "last_date": last_supply[program.id].get(supply),
                    "selected_items": [],
                    "last_items": [],
                }

        programs_data.append({
            "program": program,
            "meal_types": meal_types,
            "total_meals": total_meals,
            "has_menu": program.id in program_menu_days,
            "supply_checks": supply_checks,
        })

    return {
        "serving_programs": serving_programs,
        "prep_components": prep_components,
        "checked_items": checked_items,
        "programs_data": programs_data,
        "produce_items": produce_items,
    }


@router.get("/production")
async def production_daily_view(
    request: Request,
    date_str: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_or_worker),
):
    """Daily production sheet — viewable by admin and worker."""
    tenant_id = request.state.tenant_id

    if date_str:
        try:
            service_date = date.fromisoformat(date_str)
        except ValueError:
            service_date = date.today()
    else:
        service_date = date.today()

    data = await _build_production_data(db, tenant_id, service_date)

    prev_date = service_date - timedelta(days=1)
    next_date = service_date + timedelta(days=1)

    # Checked-item lookup key helper used in template
    # Pass as JSON so JS can also use it for optimistic UI updates
    checked_keys = [
        {
            "check_type": k[0],
            "program_id": k[1],
            "reference_key": k[2],
            "checked_at": v.checked_at.strftime("%b %d %H:%M") if v.checked_at else "",
        }
        for k, v in data["checked_items"].items()
    ]

    base_template = "worker_base.html" if user.role == "worker" else "base.html"

    return templates.TemplateResponse(
        "catering/production_daily.html",
        {
            "request": request,
            "user": user,
            "base_template": base_template,
            "service_date": service_date,
            "prev_date": prev_date.isoformat(),
            "next_date": next_date.isoformat(),
            "is_today": service_date == date.today(),
            "serving_programs": data["serving_programs"],
            "prep_components": data["prep_components"],
            "programs_data": data["programs_data"],
            "checked_keys_json": json.dumps(checked_keys),
            "supply_types": SUPPLY_TYPES,
            "produce_items": data["produce_items"],
        },
    )


@router.post("/production/toggle")
async def toggle_production_check(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_or_worker),
):
    """
    Toggle a production check on/off.
    Body: {date, check_type, program_id (optional), reference_key (optional)}
    Returns: {checked: bool, checked_at: str}
    """
    tenant_id = request.state.tenant_id
    body = await request.json()

    date_str = body.get("date")
    check_type = body.get("check_type")
    program_id = body.get("program_id") or None
    reference_key = body.get("reference_key") or None

    if not date_str or not check_type:
        return JSONResponse({"error": "date and check_type required"}, status_code=400)

    try:
        service_date = date.fromisoformat(date_str)
    except ValueError:
        return JSONResponse({"error": "invalid date"}, status_code=400)

    # Find existing log
    query = select(ProductionDailyLog).where(
        ProductionDailyLog.tenant_id == tenant_id,
        ProductionDailyLog.service_date == service_date,
        ProductionDailyLog.check_type == check_type,
    )
    if program_id:
        query = query.where(ProductionDailyLog.program_id == program_id)
    else:
        query = query.where(ProductionDailyLog.program_id == None)  # noqa: E711
    if reference_key:
        query = query.where(ProductionDailyLog.reference_key == reference_key)
    else:
        query = query.where(ProductionDailyLog.reference_key == None)  # noqa: E711

    result = await db.execute(query)
    existing = result.scalar_one_or_none()

    if existing:
        await db.delete(existing)
        await db.commit()
        return JSONResponse({"checked": False, "checked_at": ""})
    else:
        now = datetime.utcnow()
        new_log = ProductionDailyLog(
            id=str(_uuid.uuid4()),
            tenant_id=tenant_id,
            service_date=service_date,
            program_id=program_id,
            check_type=check_type,
            reference_key=reference_key,
            checked_by_user_id=user.id,
            checked_at=now,
        )
        db.add(new_log)
        await db.commit()
        return JSONResponse({"checked": True, "checked_at": now.strftime("%b %d %H:%M")})


@router.post("/production/produce-save")
async def save_produce_selection(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_or_worker),
):
    """
    Save produce item selection for a program on a given date.
    Body: {date, program_id, items: ["Apple", "Carrot", ...]}
    Empty items list = clear the produce log.
    Returns: {checked: bool, checked_at: str, items: [...]}
    """
    tenant_id = request.state.tenant_id
    body = await request.json()

    date_str = body.get("date")
    program_id = body.get("program_id")
    items = body.get("items", [])

    if not date_str or not program_id:
        return JSONResponse({"error": "date and program_id required"}, status_code=400)

    try:
        service_date = date.fromisoformat(date_str)
    except ValueError:
        return JSONResponse({"error": "invalid date"}, status_code=400)

    # Delete any existing produce log for this program+date
    existing_result = await db.execute(
        select(ProductionDailyLog).where(
            ProductionDailyLog.tenant_id == tenant_id,
            ProductionDailyLog.service_date == service_date,
            ProductionDailyLog.check_type == "produce",
            ProductionDailyLog.program_id == program_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        await db.delete(existing)

    if not items:
        await db.commit()
        return JSONResponse({"checked": False, "checked_at": "", "items": []})

    now = datetime.utcnow()
    new_log = ProductionDailyLog(
        id=str(_uuid.uuid4()),
        tenant_id=tenant_id,
        service_date=service_date,
        program_id=program_id,
        check_type="produce",
        reference_key=json.dumps(sorted(items)),
        checked_by_user_id=user.id,
        checked_at=now,
    )
    db.add(new_log)
    await db.commit()
    return JSONResponse({
        "checked": True,
        "checked_at": now.strftime("%b %d %H:%M"),
        "items": sorted(items),
    })
