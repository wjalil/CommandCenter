"""
Catering Production Routes

Daily production sheet for kitchen workers and admins.
Accessible to both admin and worker roles.
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional
import calendar
import json
import re

from app.db import get_db
from app.auth.dependencies import get_current_admin_or_worker, get_current_admin_user
from app.models.user import User
from app.models.catering import (
    CateringProgram,
    CateringMonthlyMenu,
    CateringMenuDay,
    CateringMealItem,
    CateringMealComponent,
    MenuDayComponent,
    ProductionDailyLog,
    DailyManifest,
    DailyManifestStop,
    DailyManifestItem,
    CateringDailyCount,
)
from app.models.catering.food_component import FoodComponent
from app.models.catering.cacfp_rules import CACFPComponentType
from app.crud.catering import daily_count as daily_count_crud
from app.crud.catering import invoice as invoice_crud
import uuid as _uuid

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

SUPPLY_TYPES = ["produce", "milk", "juice"]

# Production-sheet checkboxes that auto-populate line(s) on the driver manifest.
# Meal-slot checkboxes (breakfast/lunch/snack/am_snack/pm_snack) live on the
# route-delivery meal pills: a slot with a program-level pack note (currently
# only breakfast/lunch support one) adds that single bulk line (e.g. "5 trays
# breakfast"); a slot with no pack note instead adds one line per actual food
# item scheduled on that day's menu (e.g. "Pretzels", "Yogurt" for snack) —
# so itemized slots like snack don't need a note field at all.
MEAL_SLOT_TYPES = ("breakfast", "lunch", "snack", "am_snack", "pm_snack")
PACK_NOTE_FIELDS = {"breakfast": "breakfast_pack_note", "lunch": "lunch_pack_note"}
SIMPLE_SUPPLY_LABELS = {"milk": "Milk", "juice": "Juice"}
SLOT_LABELS = {
    "breakfast": "B",
    "lunch": "L",
    "snack": "S",
    "am_snack": "AM",
    "pm_snack": "PM",
}
SLOT_COLORS = {
    "breakfast": "#FD7E14",
    "lunch": "#4C6EF5",
    "snack": "#12B886",
    "am_snack": "#F5A623",
    "pm_snack": "#7048E8",
    "other": "#868E96",
}

# Distinct colors cycled per top-level route (e.g. "R1" from "R1-4"), so every
# stop on the same route reads as one visual group on screen and on the printout.
ROUTE_COLORS = ["#2563EB", "#7C3AED", "#DB2777", "#EA580C", "#16A34A", "#0891B2", "#CA8A04", "#DC2626"]


def _natural_key(s: str):
    """Sort key that orders 'R1-2' before 'R1-10' (plain string sort would not)."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s or "")]


def _route_group_key(route_code: str) -> str:
    """Top-level route used for color grouping only, e.g. 'R1-4' -> 'R1'."""
    if not route_code:
        return ""
    return route_code.split("-")[0].strip()


def _group_programs_by_route(programs_data: list) -> list:
    """Group program delivery cards by route_code, naturally sorted, one color per top-level route."""
    groups: dict = {}
    for pd in programs_data:
        route_code = (pd["program"].route_code or "").strip()
        groups.setdefault(route_code, []).append(pd)

    ordered_codes = sorted((c for c in groups if c), key=_natural_key)

    color_map: dict = {}
    result = []
    for code in ordered_codes:
        top = _route_group_key(code) or code
        if top not in color_map:
            color_map[top] = ROUTE_COLORS[len(color_map) % len(ROUTE_COLORS)]
        result.append({"route_code": code, "color": color_map[top], "programs": groups[code]})
    if "" in groups:
        result.append({"route_code": "Unassigned", "color": "#94A3B8", "programs": groups[""]})
    return result


def _effective_slot_counts(program, overrides_for_program: dict) -> tuple[dict, dict]:
    """Per-slot (count, vegan) dicts for one program on one date — uses today's
    CateringDailyCount override when present, else the program's standing count.
    Single source of truth for kitchen-prep quantities, the delivery pill counts,
    and (via crud.catering.invoice) invoice generation, so editing a headcount on
    the Production Sheet flows through everywhere that count is used."""
    counts = {
        "breakfast": program.breakfast_count if program.breakfast_count is not None else program.total_children,
        "lunch": program.lunch_count if program.lunch_count is not None else program.total_children,
        "snack": program.snack_count if program.snack_count is not None else program.total_children,
        "am_snack": program.am_snack_count if program.am_snack_count is not None else program.total_children,
        "pm_snack": program.pm_snack_count if program.pm_snack_count is not None else program.total_children,
    }
    vegan = {
        "breakfast": program.breakfast_vegan_count or 0,
        "lunch": program.lunch_vegan_count or 0,
        "snack": 0,
        "am_snack": 0,
        "pm_snack": 0,
    }
    for slot, override in (overrides_for_program or {}).items():
        counts[slot] = override.count
        vegan[slot] = override.vegan_count
    return counts, vegan


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

    # Same-day headcount overrides edited on the Production Sheet (falls back to
    # each program's standing count where no override exists for a slot).
    daily_count_overrides = await daily_count_crud.get_counts_for_date(db, tenant_id, service_date)

    # Food components whose CACFP type contains "fruit" — pulled out of the
    # per-slot Kitchen Prep buckets into their own standalone Produce section,
    # since fruit is prepped/portioned separately from the rest of a meal.
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
    produce_set = set(produce_items)

    def _accumulate(agg: dict, name: str, qty_oz: float, meal_count: int, slot: str, program_name: str):
        agg[name]["total_oz"] += qty_oz * meal_count
        agg[name]["total_count"] += meal_count
        agg[name]["slots"].add(slot)
        pb = agg[name]["program_breakdown"].setdefault(program_name, {"count": 0, "oz": 0.0})
        pb["count"] += meal_count
        pb["oz"] += qty_oz * meal_count

    # Aggregate components across all programs — produce goes to its own bucket,
    # everything else to the regular kitchen-prep bucket.
    # program_breakdown is a dict {program_name: {count, oz}} during aggregation
    component_agg: dict = defaultdict(lambda: {"total_oz": 0.0, "total_count": 0, "slots": set(), "program_breakdown": {}})
    produce_agg: dict = defaultdict(lambda: {"total_oz": 0.0, "total_count": 0, "slots": set(), "program_breakdown": {}})

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

        counts, _ = _effective_slot_counts(program, daily_count_overrides.get(program.id))

        slots_with_components = {
            comp.meal_slot for comp in menu_day.components
            if not comp.is_vegan and comp.food_component
        }
        slot_items = {
            "breakfast": menu_day.breakfast_item,
            "lunch": menu_day.lunch_item,
            "snack": menu_day.snack_item,
            "am_snack": menu_day.am_snack_item,
            "pm_snack": menu_day.pm_snack_item,
        }

        for comp in menu_day.components:
            if comp.is_vegan or not comp.food_component:
                continue
            slot = comp.meal_slot
            if slot not in meal_types_lower:
                continue
            qty_oz = float(comp.quantity or comp.food_component.default_portion_oz or 0)
            meal_count = counts.get(slot, program.total_children) or 0
            name = comp.food_component.name
            target = produce_agg if name in produce_set else component_agg
            _accumulate(target, name, qty_oz, meal_count, slot, program.name)

        for slot, meal_item in slot_items.items():
            if slot in slots_with_components:
                continue
            if slot not in meal_types_lower or not meal_item or not meal_item.components:
                continue
            meal_count = counts.get(slot, program.total_children) or 0
            for mc in meal_item.components:
                if not mc.food_component:
                    continue
                name = mc.food_component.name
                item_oz = float(mc.portion_oz or 0)
                target = produce_agg if name in produce_set else component_agg
                _accumulate(target, name, item_oz, meal_count, slot, program.name)

    def _format_agg(agg: dict) -> list:
        """Sort an aggregation bucket and convert its slot sets into sorted label lists."""
        slot_order = list(SLOT_LABELS.keys())
        formatted = []
        for name, data in sorted(agg.items()):
            slots_sorted = sorted(data["slots"], key=lambda s: slot_order.index(s) if s in slot_order else 99)
            formatted.append({
                "name": name,
                "total_oz": round(data["total_oz"], 1),
                "total_lb": round(data["total_oz"] / 16, 2),
                "total_count": data["total_count"],
                "slots": slots_sorted,
                "slot_labels": [SLOT_LABELS.get(s, s) for s in slots_sorted],
                "slot_badges": [
                    {"slot": s, "label": SLOT_LABELS.get(s, s), "color": SLOT_COLORS.get(s, SLOT_COLORS["other"])}
                    for s in slots_sorted
                ],
                "primary_slot": slots_sorted[0] if slots_sorted else "other",
                "program_breakdown": [
                    {"name": pname, "count": vals["count"], "oz": round(vals["oz"], 1), "lb": round(vals["oz"] / 16, 2)}
                    for pname, vals in sorted(data["program_breakdown"].items())
                ],
            })
        return formatted

    prep_components = _format_agg(component_agg)
    produce_components = _format_agg(produce_agg)

    # Load today's driver manifests — one per top-level route (e.g. "R1"), each
    # containing one "stop" per program on that route, each stop holding its own items.
    manifests_result = await db.execute(
        select(DailyManifest).where(
            DailyManifest.tenant_id == tenant_id,
            DailyManifest.service_date == service_date,
        )
    )
    manifest_by_route: dict = {m.route_code: m for m in manifests_result.scalars().all()}

    stops_result = await db.execute(
        select(DailyManifestStop)
        .join(DailyManifest, DailyManifestStop.manifest_id == DailyManifest.id)
        .where(
            DailyManifest.tenant_id == tenant_id,
            DailyManifest.service_date == service_date,
        )
        .options(selectinload(DailyManifestStop.items))
    )
    stop_by_program: dict = {s.program_id: s for s in stops_result.scalars().all()}

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

        # Per-meal-type counts + vegan sub-counts for the route delivery sheet —
        # reflects today's edited headcount (CateringDailyCount) where set.
        slot_counts, slot_vegan = _effective_slot_counts(program, daily_count_overrides.get(program.id))
        total_meals = max(
            [v for k, v in slot_counts.items() if k in meal_types_lower and v is not None],
            default=program.total_children or 0,
        )

        # Packaging: every required meal slot broken into its individual, checkable
        # components — the itemized, "exactly what's going into this" build-out that
        # both drives the driver manifest (see _sync_manifest_component) and doubles
        # as the per-program headcount display (replacing the old single-pill count).
        menu_day = program_menu_days.get(program.id)
        packaging_slots = []
        for slot in SLOT_ORDER:
            if slot not in meal_types_lower:
                continue
            slot_total = slot_counts.get(slot) or 0
            slot_veg = slot_vegan.get(slot, 0)

            # Produce is packed via the dedicated Produce supply check below, not as
            # a breakfast/lunch ingredient line — CACFP requires it be served, but
            # from a packaging standpoint it doesn't belong on this checklist.
            component_names = _slot_component_names_from_menu_day(menu_day, slot) if menu_day else []
            component_names = [n for n in component_names if n not in produce_set]
            if not component_names:
                component_names = [SLOT_DISPLAY.get(slot, slot.replace("_", " ").title())]
            components = [
                {"name": name, "checked": (slot, program.id, name) in checked_items}
                for name in component_names
            ]
            checked_count = sum(1 for c in components if c["checked"])

            packaging_slots.append({
                "slot": slot,
                "label": SLOT_DISPLAY.get(slot, slot.title()),
                "count": slot_total,
                "vegan": slot_veg,
                # Vegan is a subset of count, not additional to it — surface the
                # non-vegan remainder explicitly so "66 Lunch · 6 vegan" (ambiguous:
                # is that 66+6 or 66 of which 6 are vegan?) can't be misread by
                # whoever is portioning meals.
                "regular": max(slot_total - slot_veg, 0),
                "color": SLOT_COLORS.get(slot, SLOT_COLORS["other"]),
                "pack_note": getattr(program, PACK_NOTE_FIELDS[slot], None) if slot in PACK_NOTE_FIELDS else None,
                "components": components,
                "checked_count": checked_count,
                "total_components": len(components),
                "all_checked": checked_count == len(components) and len(components) > 0,
                # Whether today's count has been edited away from the program's standing count.
                "is_override": slot in (daily_count_overrides.get(program.id) or {}),
            })

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

        route_group_code = _route_group_key(program.route_code)
        manifest = manifest_by_route.get(route_group_code) if route_group_code else None
        stop = stop_by_program.get(program.id)

        programs_data.append({
            "program": program,
            "meal_types": meal_types,
            "total_meals": total_meals,
            "packaging": packaging_slots,
            "has_menu": program.id in program_menu_days,
            "supply_checks": supply_checks,
            "route_group_code": route_group_code,
            "manifest_status": manifest.status if manifest else None,
            "manifest_item_count": len(stop.items) if stop else 0,
        })

    # Vegan headcount, broken down by program (program.vegan_count is filled in per-program)
    vegan_breakdown = [
        {"name": program.name, "count": program.vegan_count}
        for program in serving_programs
        if program.vegan_count
    ]
    vegan_total = sum(vb["count"] for vb in vegan_breakdown)

    total_routes = len({pd["route_group_code"] for pd in programs_data if pd["route_group_code"]})
    released_routes = len({
        pd["route_group_code"] for pd in programs_data
        if pd["route_group_code"] and pd["manifest_status"] == "released"
    })

    return {
        "serving_programs": serving_programs,
        "prep_components": prep_components,
        "produce_components": produce_components,
        "checked_items": checked_items,
        "programs_data": programs_data,
        "route_groups": _group_programs_by_route(programs_data),
        "produce_items": produce_items,
        "vegan_total": vegan_total,
        "vegan_breakdown": vegan_breakdown,
        "manifests_released_count": released_routes,
        "manifests_total_routes": total_routes,
    }


SLOT_ORDER = list(SLOT_LABELS.keys())
SLOT_DISPLAY = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "snack": "Snack",
    "am_snack": "AM Snack",
    "pm_snack": "PM Snack",
    "other": "Other",
}


def _sort_key_for_comp(comp):
    slot = comp.get("primary_slot", "other")
    try:
        return (SLOT_ORDER.index(slot), comp["name"])
    except ValueError:
        return (99, comp["name"])


def _merge_component_lists(base: list, extras: list) -> list:
    """Combine one formatted component list (from _format_agg) with any number of
    others from additional days — used by Batch Prep Mode to total prep quantities
    across several selected service dates."""
    merged: dict = {comp["name"]: {**comp} for comp in base}
    for extra_list in extras:
        for comp in extra_list:
            if comp["name"] in merged:
                m = merged[comp["name"]]
                m["total_oz"] = round(m["total_oz"] + comp["total_oz"], 1)
                m["total_count"] += comp["total_count"]
                for lbl in comp["slot_labels"]:
                    if lbl not in m["slot_labels"]:
                        m["slot_labels"].append(lbl)
                bd = {p["name"]: {**p} for p in m["program_breakdown"]}
                for p in comp["program_breakdown"]:
                    if p["name"] in bd:
                        bd[p["name"]]["count"] += p["count"]
                        bd[p["name"]]["oz"] = round(bd[p["name"]]["oz"] + p["oz"], 1)
                    else:
                        bd[p["name"]] = {**p}
                m["program_breakdown"] = sorted(bd.values(), key=lambda x: x["name"])
            else:
                merged[comp["name"]] = {**comp, "program_breakdown": [{**p} for p in comp["program_breakdown"]]}
    return sorted(merged.values(), key=_sort_key_for_comp)


def _group_comps_by_slot(comps: list) -> list:
    """Return [{slot, slot_label, items}] in meal-type order.

    A component prepped for multiple meal slots (e.g. milk served at both
    breakfast and PM snack) is listed under every slot it's actually used in,
    not just the earliest one — otherwise later slots (like PM snack) would
    silently drop items that also happen to appear earlier in the day.
    """
    grouped: dict = {}
    for comp in sorted(comps, key=_sort_key_for_comp):
        slots = comp.get("slots") or [comp.get("primary_slot", "other")]
        for slot in slots:
            grouped.setdefault(slot, []).append(comp)
    result = []
    for slot in SLOT_ORDER + ["other"]:
        if slot in grouped:
            result.append({
                "slot": slot,
                "slot_label": SLOT_DISPLAY.get(slot, slot.title()),
                "color": SLOT_COLORS.get(slot, SLOT_COLORS["other"]),
                "items": grouped[slot],
            })
    return result


@router.get("/production")
async def production_daily_view(
    request: Request,
    date_str: Optional[str] = None,
    selected: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_or_worker),
):
    """Daily production sheet — viewable by admin and worker."""
    tenant_id = request.state.tenant_id
    today = date.today()

    # anchor_date drives which week is displayed
    try:
        anchor_date = date.fromisoformat(date_str) if date_str else today
    except ValueError:
        anchor_date = today

    # Parse comma-separated selected dates; default to anchor_date
    selected_dates: list[date] = []
    if selected:
        for s in selected.split(","):
            try:
                selected_dates.append(date.fromisoformat(s.strip()))
            except ValueError:
                pass
    selected_dates = sorted(set(selected_dates)) or [anchor_date]

    # Primary date (earliest selected) drives delivery tracking
    primary_date = selected_dates[0]

    # Week view: Mon–Sun of the week containing anchor_date
    week_start = anchor_date - timedelta(days=anchor_date.weekday())
    week_dates = [week_start + timedelta(days=i) for i in range(7)]
    prev_week_anchor = (week_start - timedelta(days=7)).isoformat()
    next_week_anchor = (week_start + timedelta(days=7)).isoformat()
    selected_iso = [d.isoformat() for d in selected_dates]

    # Build production data for primary date (delivery + checked states)
    data = await _build_production_data(db, tenant_id, primary_date)

    # Batch Prep Mode: combine prep quantities across several selected days (e.g.
    # summer batch-cooking a week at once). Off by default — a single selected date
    # (the normal case) just sorts and moves on, no merging.
    is_batch_mode = len(selected_dates) > 1
    if is_batch_mode:
        extra_data = [await _build_production_data(db, tenant_id, d) for d in selected_dates[1:]]
        data["prep_components"] = _merge_component_lists(
            data["prep_components"], [d["prep_components"] for d in extra_data]
        )
        data["produce_components"] = _merge_component_lists(
            data["produce_components"], [d["produce_components"] for d in extra_data]
        )
    else:
        data["prep_components"] = sorted(data["prep_components"], key=_sort_key_for_comp)
        data["produce_components"] = sorted(data["produce_components"], key=_sort_key_for_comp)

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
            "anchor_date": anchor_date,
            "primary_date": primary_date,
            "selected_dates": selected_dates,
            "selected_iso": selected_iso,
            "is_batch_mode": is_batch_mode,
            "week_dates": week_dates,
            "prev_week_anchor": prev_week_anchor,
            "next_week_anchor": next_week_anchor,
            "is_current_week": week_start == (today - timedelta(days=today.weekday())),
            "serving_programs": data["serving_programs"],
            "prep_components": data["prep_components"],
            "prep_by_slot": _group_comps_by_slot(data["prep_components"]),
            "produce_components": data["produce_components"],
            "programs_data": data["programs_data"],
            "route_groups": data["route_groups"],
            "checked_keys_json": json.dumps(checked_keys),
            "supply_types": SUPPLY_TYPES,
            "produce_items": data["produce_items"],
            "vegan_total": data["vegan_total"],
            "vegan_breakdown": data["vegan_breakdown"],
            "manifests_released_count": data["manifests_released_count"],
            "manifests_total_routes": data["manifests_total_routes"],
        },
    )


@router.get("/production/print")
async def production_print_view(
    request: Request,
    month: Optional[int] = None,
    year: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_or_worker),
):
    """Printable production sheet for the kitchen: one page per serving day in the month,
    split into a Cook half (ingredient totals to prep) and a Portion half (route/delivery
    breakdown). Rendered as a plain HTML page (fast) — use the browser's print dialog
    (or the on-page Print button) to get a paper/PDF copy instead of generating one server-side."""
    tenant_id = request.state.tenant_id
    today = date.today()
    month = month or today.month
    year = year or today.year

    days_in_month = calendar.monthrange(year, month)[1]
    all_days = [date(year, month, d) for d in range(1, days_in_month + 1)]

    day_sheets = []
    for d in all_days:
        data = await _build_production_data(db, tenant_id, d)
        if not data["serving_programs"]:
            continue  # weekend / no service / holiday for every program — skip the page
        day_sheets.append({
            "date": d,
            "prep_by_slot": _group_comps_by_slot(data["prep_components"]),
            "produce_components": sorted(data["produce_components"], key=lambda c: c["name"]),
            "vegan_total": data["vegan_total"],
            "vegan_breakdown": data["vegan_breakdown"],
            "serving_programs": data["serving_programs"],
            "programs_data": data["programs_data"],
            "route_groups": data["route_groups"],
        })

    month_label = date(year, month, 1).strftime("%B %Y")
    prev_month_date = date(year, month, 1) - timedelta(days=1)
    next_month_date = date(year, month, days_in_month) + timedelta(days=1)

    return templates.TemplateResponse(
        "catering/production_print.html",
        {
            "request": request,
            "month_label": month_label,
            "month": month,
            "year": year,
            "prev_month": prev_month_date.month,
            "prev_year": prev_month_date.year,
            "next_month": next_month_date.month,
            "next_year": next_month_date.year,
            "day_sheets": day_sheets,
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

    async def _sync_manifest(checked: bool):
        if not program_id:
            return
        if check_type in MEAL_SLOT_TYPES and reference_key:
            await _sync_manifest_component(db, tenant_id, program_id, service_date, check_type, reference_key, checked=checked)
        elif check_type in SIMPLE_SUPPLY_LABELS:
            await _sync_manifest_checkbox(db, tenant_id, program_id, service_date, check_type, checked=checked)

    if existing:
        await db.delete(existing)
        await db.commit()
        await _sync_manifest(checked=False)
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
        await _sync_manifest(checked=True)
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
        await _sync_manifest_produce(db, tenant_id, program_id, service_date, [])
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
    await _sync_manifest_produce(db, tenant_id, program_id, service_date, items)
    return JSONResponse({
        "checked": True,
        "checked_at": now.strftime("%b %d %H:%M"),
        "items": sorted(items),
    })


@router.post("/production/count-save")
async def save_daily_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """Edit a program's headcount for one meal slot on one service date — the
    source invoices and kitchen-prep quantities read from (falls back to the
    program's standing count when no override exists).
    Body: {date, program_id, slot, count, vegan_count}
    Returns: {count, vegan_count, regular, total_meals} for that program/date.
    """
    tenant_id = request.state.tenant_id
    body = await request.json()

    date_str = body.get("date")
    program_id = body.get("program_id")
    slot = body.get("slot")

    if not date_str or not program_id or slot not in MEAL_SLOT_TYPES:
        return JSONResponse({"error": "date, program_id and a valid slot are required"}, status_code=400)

    try:
        service_date = date.fromisoformat(date_str)
        count = int(body.get("count"))
        vegan_count = int(body.get("vegan_count") or 0)
    except (ValueError, TypeError):
        return JSONResponse({"error": "invalid count"}, status_code=400)

    if count < 0 or vegan_count < 0 or vegan_count > count:
        return JSONResponse({"error": "counts must be non-negative and vegan count can't exceed the total"}, status_code=400)

    program = await db.get(CateringProgram, program_id)
    if not program or program.tenant_id != tenant_id:
        return JSONResponse({"error": "program not found"}, status_code=404)

    await daily_count_crud.set_count(
        db, tenant_id, program_id, service_date, slot, count, vegan_count, user_id=user.id,
    )

    overrides = await daily_count_crud.get_counts_for_program_date(db, program_id, service_date)
    slot_counts, slot_vegan = _effective_slot_counts(program, overrides)
    meal_types = (
        json.loads(program.meal_types_required)
        if isinstance(program.meal_types_required, str)
        else (program.meal_types_required or [])
    )
    meal_types_lower = [mt.lower().replace(" ", "_") for mt in meal_types]
    total_meals = max(
        [v for k, v in slot_counts.items() if k in meal_types_lower and v is not None],
        default=program.total_children or 0,
    )

    return JSONResponse({
        "count": slot_counts[slot],
        "vegan_count": slot_vegan[slot],
        "regular": max(slot_counts[slot] - slot_vegan[slot], 0),
        "total_meals": total_meals,
    })


async def _menu_day_for_program_date(db: AsyncSession, program_id: str, service_date: date):
    """The monthly menu day for one program on one date, or None — used to check
    whether a menu exists before generating that day's invoice from it."""
    result = await db.execute(
        select(CateringMonthlyMenu)
        .where(
            CateringMonthlyMenu.program_id == program_id,
            CateringMonthlyMenu.month == service_date.month,
            CateringMonthlyMenu.year == service_date.year,
            CateringMonthlyMenu.menu_type == "regular",
        )
        .options(selectinload(CateringMonthlyMenu.menu_days))
    )
    monthly_menu = result.scalar_one_or_none()
    if not monthly_menu:
        return None
    return next((d for d in monthly_menu.menu_days if d.service_date == service_date), None)


@router.post("/production/generate-invoices")
async def generate_invoices_from_production(
    request: Request,
    date_str: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """Generate/update today's invoices for every serving program, straight from
    the kitchen — reading each program's (possibly edited) daily headcount rather
    than the planned monthly-menu count. Triggered from the Production Sheet."""
    tenant_id = request.state.tenant_id
    try:
        service_date = date.fromisoformat(date_str)
    except ValueError:
        return RedirectResponse(url="/catering/production", status_code=303)

    serving_programs = await _serving_programs_for_date(db, tenant_id, service_date)

    generated = 0
    skipped = 0
    for program in serving_programs:
        menu_day = await _menu_day_for_program_date(db, program.id, service_date)
        if not menu_day:
            skipped += 1
            continue
        invoice = await invoice_crud.generate_invoice_from_menu_day(db, menu_day.id, tenant_id)
        if invoice:
            generated += 1
        else:
            skipped += 1

    msg = f"{generated} invoice(s) generated/updated"
    if skipped:
        msg += f", {skipped} skipped (no menu set for that day)"

    return RedirectResponse(
        url=f"/catering/production?date_str={service_date.isoformat()}&message={msg}",
        status_code=303,
    )


async def _get_or_create_manifest(db: AsyncSession, tenant_id: int, route_code: str, service_date: date) -> DailyManifest:
    """Get today's manifest for a top-level route (e.g. "R1"), creating an empty draft one if needed."""
    result = await db.execute(
        select(DailyManifest).where(
            DailyManifest.tenant_id == tenant_id,
            DailyManifest.route_code == route_code,
            DailyManifest.service_date == service_date,
        )
    )
    manifest = result.scalar_one_or_none()
    if manifest:
        return manifest

    manifest = DailyManifest(
        id=str(_uuid.uuid4()),
        tenant_id=tenant_id,
        route_code=route_code,
        service_date=service_date,
        status="draft",
    )
    db.add(manifest)
    await db.flush()
    return manifest


async def _get_or_create_stop(db: AsyncSession, tenant_id: int, program: CateringProgram, service_date: date) -> DailyManifestStop:
    """Get this program's stop within its route's manifest for the day, creating both if needed.

    Never touch manifest.stops / stop.items off the returned objects — see the
    warning on _get_or_create_manifest's sibling note in _sync_manifest_checkbox;
    a delete-orphan collection still needs an (unawaitable) lazy load on first
    touch even for a just-flushed object. Query DailyManifestStop/Item directly.
    """
    route_code = _route_group_key(program.route_code) or "Unassigned"
    manifest = await _get_or_create_manifest(db, tenant_id, route_code, service_date)

    result = await db.execute(
        select(DailyManifestStop).where(
            DailyManifestStop.manifest_id == manifest.id,
            DailyManifestStop.program_id == program.id,
        )
    )
    stop = result.scalar_one_or_none()
    if stop:
        return stop

    next_order = await _manifest_stop_count(db, manifest.id)
    stop = DailyManifestStop(
        id=str(_uuid.uuid4()),
        manifest_id=manifest.id,
        program_id=program.id,
        special_instructions=program.special_instructions,
        sort_order=next_order,
    )
    db.add(stop)
    await db.flush()
    return stop


async def _manifest_stop_count(db: AsyncSession, manifest_id: str) -> int:
    result = await db.execute(
        select(func.count()).select_from(DailyManifestStop).where(DailyManifestStop.manifest_id == manifest_id)
    )
    return result.scalar() or 0


async def _stop_item_count(db: AsyncSession, stop_id: str) -> int:
    result = await db.execute(
        select(func.count()).select_from(DailyManifestItem).where(DailyManifestItem.stop_id == stop_id)
    )
    return result.scalar() or 0


def _slot_component_names_from_menu_day(menu_day, slot: str) -> list:
    """Actual food item names scheduled for one meal slot on an already-loaded menu
    day (e.g. slot='snack' -> ['Pretzels', 'Yogurt']) — same override-vs-fallback
    lookup used for kitchen prep aggregation, scoped to one slot, reading off an
    object already in memory rather than re-querying."""
    if not menu_day:
        return []
    names, seen = [], set()
    comps = [c for c in menu_day.components if c.meal_slot == slot and not c.is_vegan and c.food_component]
    if comps:
        for c in comps:
            if c.food_component.name not in seen:
                seen.add(c.food_component.name)
                names.append(c.food_component.name)
        return names

    meal_item = getattr(menu_day, f"{slot}_item", None)
    if meal_item and meal_item.components:
        for mc in meal_item.components:
            if mc.food_component and mc.food_component.name not in seen:
                seen.add(mc.food_component.name)
                names.append(mc.food_component.name)
    return names


async def _sync_manifest_checkbox(db: AsyncSession, tenant_id: int, program_id: str, service_date: date, source: str, checked: bool):
    """Add/remove the manifest line for a simple supply checkbox (milk/juice) — one
    plain line, e.g. "Milk" — under this program's stop within its route's manifest.
    Meal slots (breakfast/lunch/snack/am_snack/pm_snack) are handled per-component
    by _sync_manifest_component instead."""
    program = await db.get(CateringProgram, program_id)
    if not program:
        return

    label = SIMPLE_SUPPLY_LABELS.get(source)
    if label is None:
        return

    if checked:
        stop = await _get_or_create_stop(db, tenant_id, program, service_date)
        existing_result = await db.execute(
            select(DailyManifestItem.id).where(
                DailyManifestItem.stop_id == stop.id,
                DailyManifestItem.source == source,
            ).limit(1)
        )
        if existing_result.scalar_one_or_none() is None:
            next_order = await _stop_item_count(db, stop.id)
            db.add(DailyManifestItem(
                id=str(_uuid.uuid4()),
                stop_id=stop.id,
                source=source,
                label=label,
                sort_order=next_order,
            ))
            await db.commit()
    else:
        route_code = _route_group_key(program.route_code) or "Unassigned"
        stop_result = await db.execute(
            select(DailyManifestStop)
            .join(DailyManifest, DailyManifestStop.manifest_id == DailyManifest.id)
            .where(
                DailyManifest.tenant_id == tenant_id,
                DailyManifest.route_code == route_code,
                DailyManifest.service_date == service_date,
                DailyManifestStop.program_id == program_id,
            )
        )
        stop = stop_result.scalar_one_or_none()
        if not stop:
            return
        item_result = await db.execute(
            select(DailyManifestItem).where(
                DailyManifestItem.stop_id == stop.id,
                DailyManifestItem.source == source,
            )
        )
        for existing_item in item_result.scalars().all():
            await db.delete(existing_item)
        await db.commit()


async def _sync_manifest_component(db: AsyncSession, tenant_id: int, program_id: str, service_date: date, slot: str, component_name: str, checked: bool):
    """Sync the manifest when a packaging checkbox is toggled on the Packaging screen.

    Breakfast/Lunch (slots with a pack-note field): the manifest only ever carries
    the single bulk pack-note line (e.g. "5 trays breakfast") — individual
    ingredient checks stay on the Packaging screen for the kitchen's own tracking,
    they never become separate manifest lines, since a driver doesn't need an
    ingredient-level breakdown for a pre-packed tray. The pack-note line is present
    once at least one ingredient for that slot is checked, removed once none are.

    Snack/AM snack/PM snack (no pack note): unchanged — each ingredient is its own
    manifest line, since these are handed out as individual items, not bulk trays.
    """
    program = await db.get(CateringProgram, program_id)
    if not program:
        return

    stop = await _get_or_create_stop(db, tenant_id, program, service_date)
    pack_note_field = PACK_NOTE_FIELDS.get(slot)

    if pack_note_field:
        note = getattr(program, pack_note_field, None)
        if not note:
            return

        checked_count_result = await db.execute(
            select(func.count()).select_from(ProductionDailyLog).where(
                ProductionDailyLog.tenant_id == tenant_id,
                ProductionDailyLog.service_date == service_date,
                ProductionDailyLog.check_type == slot,
                ProductionDailyLog.program_id == program_id,
            )
        )
        any_checked = (checked_count_result.scalar() or 0) > 0

        packnote_source = f"{slot}_packnote"
        packnote_result = await db.execute(
            select(DailyManifestItem).where(
                DailyManifestItem.stop_id == stop.id,
                DailyManifestItem.source == packnote_source,
            )
        )
        packnote_item = packnote_result.scalar_one_or_none()

        if any_checked and not packnote_item:
            next_order = await _stop_item_count(db, stop.id)
            db.add(DailyManifestItem(
                id=str(_uuid.uuid4()),
                stop_id=stop.id,
                source=packnote_source,
                label=note,
                sort_order=next_order,
            ))
        elif not any_checked and packnote_item:
            await db.delete(packnote_item)
    else:
        existing_result = await db.execute(
            select(DailyManifestItem).where(
                DailyManifestItem.stop_id == stop.id,
                DailyManifestItem.source == slot,
                DailyManifestItem.label == component_name,
            )
        )
        existing_item = existing_result.scalar_one_or_none()

        if checked and not existing_item:
            next_order = await _stop_item_count(db, stop.id)
            db.add(DailyManifestItem(
                id=str(_uuid.uuid4()),
                stop_id=stop.id,
                source=slot,
                label=component_name,
                sort_order=next_order,
            ))
        elif not checked and existing_item:
            await db.delete(existing_item)

    await db.commit()


async def _sync_manifest_produce(db: AsyncSession, tenant_id: int, program_id: str, service_date: date, items: list):
    """Replace this program's stop's produce lines with the current produce selection."""
    program = await db.get(CateringProgram, program_id)
    if not program:
        return
    route_code = _route_group_key(program.route_code) or "Unassigned"

    stop_result = await db.execute(
        select(DailyManifestStop)
        .join(DailyManifest, DailyManifestStop.manifest_id == DailyManifest.id)
        .where(
            DailyManifest.tenant_id == tenant_id,
            DailyManifest.route_code == route_code,
            DailyManifest.service_date == service_date,
            DailyManifestStop.program_id == program_id,
        )
    )
    stop = stop_result.scalar_one_or_none()

    if not items:
        if not stop:
            return
        item_result = await db.execute(
            select(DailyManifestItem).where(
                DailyManifestItem.stop_id == stop.id,
                DailyManifestItem.source == "produce",
            )
        )
        for existing_item in item_result.scalars().all():
            await db.delete(existing_item)
        await db.commit()
        return

    if not stop:
        stop = await _get_or_create_stop(db, tenant_id, program, service_date)

    item_result = await db.execute(
        select(DailyManifestItem).where(
            DailyManifestItem.stop_id == stop.id,
            DailyManifestItem.source == "produce",
        )
    )
    for existing_item in item_result.scalars().all():
        await db.delete(existing_item)
    await db.flush()

    base_order = 1000
    for i, name in enumerate(sorted(items)):
        db.add(DailyManifestItem(
            id=str(_uuid.uuid4()),
            stop_id=stop.id,
            source="produce",
            label=name,
            sort_order=base_order + i,
        ))
    await db.commit()


# ==================== MANIFEST BUILDER (admin) ====================

async def _serving_programs_for_date(db: AsyncSession, tenant_id: int, service_date: date) -> list:
    """Active programs whose service_days include this date's weekday and who
    aren't on holiday that day — same filter used to build the production sheet."""
    programs_result = await db.execute(
        select(CateringProgram)
        .where(CateringProgram.tenant_id == tenant_id, CateringProgram.is_active == True)
        .options(selectinload(CateringProgram.holidays))
        .order_by(CateringProgram.route_code, CateringProgram.name)
    )
    all_programs = programs_result.scalars().all()

    day_name = service_date.strftime("%A")
    serving = []
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
        serving.append(program)
    return serving


@router.get("/production/manifest/builder")
async def manifest_builder(
    request: Request,
    date_str: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """One consolidated admin screen: every route serving today, each with its stops
    and their items, editable inline, with a release toggle per route."""
    tenant_id = request.state.tenant_id
    try:
        service_date = date.fromisoformat(date_str) if date_str else date.today()
    except ValueError:
        service_date = date.today()

    serving_programs = await _serving_programs_for_date(db, tenant_id, service_date)

    # Ensure every serving route+stop has a row to attach manual items/instructions to.
    for program in serving_programs:
        if program.route_code:
            await _get_or_create_stop(db, tenant_id, program, service_date)

    manifests_result = await db.execute(
        select(DailyManifest)
        .where(
            DailyManifest.tenant_id == tenant_id,
            DailyManifest.service_date == service_date,
        )
        .options(
            selectinload(DailyManifest.stops).selectinload(DailyManifestStop.program),
            selectinload(DailyManifest.stops).selectinload(DailyManifestStop.items),
        )
        .order_by(DailyManifest.route_code)
    )
    manifests = manifests_result.scalars().all()
    manifest_cards = [
        {
            "manifest": m,
            "stops": sorted(m.stops, key=lambda s: _natural_key(s.program.route_code or "") if s.program else ""),
        }
        for m in sorted(manifests, key=lambda m: _natural_key(m.route_code))
    ]

    return templates.TemplateResponse("catering/production_manifest_builder.html", {
        "request": request,
        "service_date": service_date,
        "manifest_cards": manifest_cards,
    })


@router.post("/production/manifest/stop/{stop_id}/items")
async def manifest_add_item(
    request: Request,
    stop_id: str,
    label: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """Add a one-off manual line item to a stop."""
    tenant_id = request.state.tenant_id
    result = await db.execute(
        select(DailyManifestStop)
        .join(DailyManifest, DailyManifestStop.manifest_id == DailyManifest.id)
        .where(DailyManifestStop.id == stop_id, DailyManifest.tenant_id == tenant_id)
    )
    stop = result.scalar_one_or_none()

    date_str = ""
    if stop and label.strip():
        next_order = await _stop_item_count(db, stop.id)
        db.add(DailyManifestItem(
            id=str(_uuid.uuid4()),
            stop_id=stop.id,
            source="manual",
            label=label.strip(),
            sort_order=next_order,
        ))
        manifest_result = await db.execute(select(DailyManifest).where(DailyManifest.id == stop.manifest_id))
        manifest = manifest_result.scalar_one_or_none()
        if manifest:
            date_str = manifest.service_date.isoformat()
        await db.commit()

    return RedirectResponse(url=f"/catering/production/manifest/builder?date_str={date_str}", status_code=303)


@router.post("/production/manifest/item/{item_id}/edit")
async def manifest_edit_item(
    request: Request,
    item_id: str,
    label: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """Edit a line item's text — e.g. annotate an auto-added 'Yogurt' line into 'Yogurt — 4 boxes'."""
    tenant_id = request.state.tenant_id
    result = await db.execute(
        select(DailyManifestItem)
        .join(DailyManifestStop, DailyManifestItem.stop_id == DailyManifestStop.id)
        .join(DailyManifest, DailyManifestStop.manifest_id == DailyManifest.id)
        .where(DailyManifestItem.id == item_id, DailyManifest.tenant_id == tenant_id)
    )
    item = result.scalar_one_or_none()

    date_str = ""
    if item and label.strip():
        item.label = label.strip()
        date_str = await _date_for_item(db, item)
        await db.commit()

    return RedirectResponse(url=f"/catering/production/manifest/builder?date_str={date_str}", status_code=303)


@router.post("/production/manifest/item/{item_id}/delete")
async def manifest_delete_item(
    request: Request,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """Remove a line item from a stop (any source — lets admin correct mistakes)."""
    tenant_id = request.state.tenant_id
    result = await db.execute(
        select(DailyManifestItem)
        .join(DailyManifestStop, DailyManifestItem.stop_id == DailyManifestStop.id)
        .join(DailyManifest, DailyManifestStop.manifest_id == DailyManifest.id)
        .where(DailyManifestItem.id == item_id, DailyManifest.tenant_id == tenant_id)
    )
    item = result.scalar_one_or_none()

    date_str = ""
    if item:
        date_str = await _date_for_item(db, item)
        await db.delete(item)
        await db.commit()

    return RedirectResponse(url=f"/catering/production/manifest/builder?date_str={date_str}", status_code=303)


async def _date_for_item(db: AsyncSession, item: DailyManifestItem) -> str:
    result = await db.execute(
        select(DailyManifest.service_date)
        .join(DailyManifestStop, DailyManifestStop.manifest_id == DailyManifest.id)
        .where(DailyManifestStop.id == item.stop_id)
    )
    service_date = result.scalar_one_or_none()
    return service_date.isoformat() if service_date else ""


@router.post("/production/manifest/stop/{stop_id}/instructions")
async def manifest_save_instructions(
    request: Request,
    stop_id: str,
    special_instructions: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """Save this stop's special-instructions note (e.g. 'Gated entrance, use side door')."""
    tenant_id = request.state.tenant_id
    result = await db.execute(
        select(DailyManifestStop)
        .join(DailyManifest, DailyManifestStop.manifest_id == DailyManifest.id)
        .where(DailyManifestStop.id == stop_id, DailyManifest.tenant_id == tenant_id)
    )
    stop = result.scalar_one_or_none()

    date_str = ""
    if stop:
        stop.special_instructions = special_instructions.strip() or None
        manifest_result = await db.execute(select(DailyManifest).where(DailyManifest.id == stop.manifest_id))
        manifest = manifest_result.scalar_one_or_none()
        if manifest:
            date_str = manifest.service_date.isoformat()
        await db.commit()

    return RedirectResponse(url=f"/catering/production/manifest/builder?date_str={date_str}", status_code=303)


@router.post("/production/manifest/{manifest_id}/release")
async def manifest_release(
    request: Request,
    manifest_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """Release a route's manifest so it becomes visible to drivers."""
    tenant_id = request.state.tenant_id
    result = await db.execute(
        select(DailyManifest).where(DailyManifest.id == manifest_id, DailyManifest.tenant_id == tenant_id)
    )
    manifest = result.scalar_one_or_none()

    date_str = ""
    if manifest:
        manifest.status = "released"
        manifest.released_at = datetime.utcnow()
        manifest.released_by_user_id = user.id
        date_str = manifest.service_date.isoformat()
        await db.commit()

    return RedirectResponse(url=f"/catering/production/manifest/builder?date_str={date_str}", status_code=303)


@router.post("/production/manifest/{manifest_id}/reopen")
async def manifest_reopen(
    request: Request,
    manifest_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """Pull a released route manifest back to draft so it can be corrected."""
    tenant_id = request.state.tenant_id
    result = await db.execute(
        select(DailyManifest).where(DailyManifest.id == manifest_id, DailyManifest.tenant_id == tenant_id)
    )
    manifest = result.scalar_one_or_none()

    date_str = ""
    if manifest:
        manifest.status = "draft"
        manifest.released_at = None
        manifest.released_by_user_id = None
        date_str = manifest.service_date.isoformat()
        await db.commit()

    return RedirectResponse(url=f"/catering/production/manifest/builder?date_str={date_str}", status_code=303)


# ==================== DRIVER MANIFEST ====================

@router.get("/production/manifest/driver/view")
async def driver_manifest_landing(
    request: Request,
    date_str: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_or_worker),
):
    """Driver landing page: pick which route's manifest to view."""
    tenant_id = request.state.tenant_id
    try:
        service_date = date.fromisoformat(date_str) if date_str else date.today()
    except ValueError:
        service_date = date.today()

    result = await db.execute(
        select(DailyManifest)
        .where(
            DailyManifest.tenant_id == tenant_id,
            DailyManifest.service_date == service_date,
            DailyManifest.status == "released",
        )
        .options(
            selectinload(DailyManifest.stops).selectinload(DailyManifestStop.items),
        )
    )
    manifests = result.scalars().all()
    manifests = sorted(manifests, key=lambda m: _natural_key(m.route_code))

    color_map: dict = {}
    routes = []
    for m in manifests:
        if m.route_code not in color_map:
            color_map[m.route_code] = ROUTE_COLORS[len(color_map) % len(ROUTE_COLORS)]
        routes.append({
            "route_code": m.route_code,
            "color": color_map[m.route_code],
            "stop_count": len(m.stops),
            "item_count": sum(len(s.items) for s in m.stops),
        })

    base_template = "worker_base.html" if user.role == "worker" else "base.html"

    return templates.TemplateResponse("catering/production_manifest_driver_landing.html", {
        "request": request,
        "base_template": base_template,
        "service_date": service_date,
        "prev_date": (service_date - timedelta(days=1)).isoformat(),
        "next_date": (service_date + timedelta(days=1)).isoformat(),
        "is_today": service_date == date.today(),
        "routes": routes,
    })


@router.get("/production/manifest/driver/view/{route_code}")
async def driver_manifest_detail(
    request: Request,
    route_code: str,
    date_str: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_or_worker),
):
    """Daily Manifest for one route — the actual stop-by-stop, paper-format view."""
    tenant_id = request.state.tenant_id
    try:
        service_date = date.fromisoformat(date_str) if date_str else date.today()
    except ValueError:
        service_date = date.today()

    result = await db.execute(
        select(DailyManifest)
        .where(
            DailyManifest.tenant_id == tenant_id,
            DailyManifest.route_code == route_code,
            DailyManifest.service_date == service_date,
            DailyManifest.status == "released",
        )
        .options(
            selectinload(DailyManifest.stops).selectinload(DailyManifestStop.program),
            selectinload(DailyManifest.stops).selectinload(DailyManifestStop.items),
        )
    )
    manifest = result.scalar_one_or_none()

    stops = []
    if manifest:
        stops = sorted(manifest.stops, key=lambda s: _natural_key(s.program.route_code or "") if s.program else "")

    base_template = "worker_base.html" if user.role == "worker" else "base.html"

    return templates.TemplateResponse("catering/production_manifest_driver.html", {
        "request": request,
        "base_template": base_template,
        "route_code": route_code,
        "service_date": service_date,
        "manifest": manifest,
        "stops": stops,
    })


@router.post("/production/manifest/item/{item_id}/confirm")
async def manifest_confirm_item(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_or_worker),
):
    """Driver toggles a manifest line as loaded/confirmed — independent of the kitchen's pack checkbox.
    Body: {item_id}
    """
    tenant_id = request.state.tenant_id
    body = await request.json()
    item_id = body.get("item_id")

    result = await db.execute(
        select(DailyManifestItem)
        .join(DailyManifestStop, DailyManifestItem.stop_id == DailyManifestStop.id)
        .join(DailyManifest, DailyManifestStop.manifest_id == DailyManifest.id)
        .where(DailyManifestItem.id == item_id, DailyManifest.tenant_id == tenant_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        return JSONResponse({"error": "not found"}, status_code=404)

    item.driver_confirmed = not item.driver_confirmed
    if item.driver_confirmed:
        item.driver_confirmed_at = datetime.utcnow()
        item.driver_confirmed_by_user_id = user.id
    else:
        item.driver_confirmed_at = None
        item.driver_confirmed_by_user_id = None
    await db.commit()

    return JSONResponse({
        "confirmed": item.driver_confirmed,
        "confirmed_at": item.driver_confirmed_at.strftime("%H:%M") if item.driver_confirmed_at else "",
    })
