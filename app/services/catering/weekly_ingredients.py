import json
from collections import defaultdict
from datetime import timedelta, date
from sqlalchemy.orm import Session, joinedload
from calendar import monthrange

from app.models.catering import CateringMenuDay, CateringMonthlyMenu, MenuDayComponent

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
SLOT_ORDER = list(SLOT_LABELS.keys())


def build_aggregate_ingredient_list(
    db: Session,
    tenant_id: int,
    year: int,
    month: int,
    program_id: str = None
):
    """
    Returns aggregated weekly ingredient list (with real quantities) across all
    programs for a month, or filtered to one program.

    Returns:
        {
            "weeks": [...],
            "programs": [list of programs included],
            "total_ingredients": int
        }
    """
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])

    query = (
        db.query(CateringMenuDay)
        .join(CateringMonthlyMenu)
        .options(
            joinedload(CateringMenuDay.components).joinedload(MenuDayComponent.food_component),
            joinedload(CateringMenuDay.monthly_menu).joinedload(CateringMonthlyMenu.program),
        )
        .filter(
            CateringMonthlyMenu.tenant_id == tenant_id,
            CateringMenuDay.service_date >= first_day,
            CateringMenuDay.service_date <= last_day
        )
    )

    if program_id:
        query = query.filter(CateringMonthlyMenu.program_id == program_id)

    menu_days = query.order_by(CateringMenuDay.service_date).all()

    programs_seen = {}
    for day in menu_days:
        if day.monthly_menu and day.monthly_menu.program:
            prog = day.monthly_menu.program
            if prog.id not in programs_seen:
                programs_seen[prog.id] = {
                    "id": prog.id,
                    "name": prog.name,
                    "client_name": prog.client_name
                }

    weeks = _process_menu_days_to_weeks(menu_days)

    all_ingredient_names = set()
    for week in weeks:
        all_ingredient_names.update(ing["name"] for ing in week["ingredients"])

    return {
        "weeks": weeks,
        "programs": list(programs_seen.values()),
        "total_ingredients": len(all_ingredient_names)
    }


def _process_menu_days_to_weeks(menu_days):
    """
    Aggregate real quantities (oz/lb) needed per ingredient per week, with a
    per-meal-slot breakdown and a per-program breakdown for each ingredient.
    """
    def _new_day_bucket():
        return {"oz": 0.0, "count": 0}

    def _new_slot_bucket():
        return {"oz": 0.0, "count": 0, "by_day": defaultdict(_new_day_bucket)}

    def _new_ingredient_bucket():
        return {
            "total_oz": 0.0,
            "total_count": 0,
            "slots": set(),
            "by_slot": defaultdict(_new_slot_bucket),
            "by_day": defaultdict(_new_day_bucket),
            "program_breakdown": {},
        }

    weeks = defaultdict(lambda: defaultdict(_new_ingredient_bucket))

    for day in menu_days:
        program = day.monthly_menu.program if day.monthly_menu else None
        if not program:
            continue

        week_start = day.service_date - timedelta(days=day.service_date.weekday())

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
        # Only breakfast/lunch have a dedicated vegan-count field on the program;
        # fall back to the legacy overall vegan_count for the other slots.
        vegan_counts = {
            "breakfast": program.breakfast_vegan_count or 0,
            "lunch": program.lunch_vegan_count or 0,
            "snack": program.vegan_count or 0,
            "am_snack": program.vegan_count or 0,
            "pm_snack": program.vegan_count or 0,
        }

        for component in day.components:
            if not component.food_component:
                continue
            slot = component.meal_slot
            if slot not in meal_types_lower:
                continue

            meal_count = (vegan_counts if component.is_vegan else counts).get(slot) or 0
            if meal_count <= 0:
                continue

            name = component.food_component.name
            qty_oz = float(component.quantity or component.food_component.default_portion_oz or 0)
            total_oz = qty_oz * meal_count

            agg = weeks[week_start][name]
            agg["total_oz"] += total_oz
            agg["total_count"] += meal_count
            agg["slots"].add(slot)

            by_slot = agg["by_slot"][slot]
            by_slot["oz"] += total_oz
            by_slot["count"] += meal_count
            by_slot["by_day"][day.service_date]["oz"] += total_oz
            by_slot["by_day"][day.service_date]["count"] += meal_count

            agg["by_day"][day.service_date]["oz"] += total_oz
            agg["by_day"][day.service_date]["count"] += meal_count

            pb = agg["program_breakdown"].setdefault(program.id, {"name": program.name, "oz": 0.0, "count": 0})
            pb["oz"] += total_oz
            pb["count"] += meal_count

    today = date.today()
    weekly_output = []
    for week_start in sorted(weeks.keys()):
        ingredients = []
        for name, agg in sorted(weeks[week_start].items()):
            slots_sorted = sorted(agg["slots"], key=lambda s: SLOT_ORDER.index(s) if s in SLOT_ORDER else 99)
            ingredients.append({
                "name": name,
                "total_oz": round(agg["total_oz"], 1),
                "total_lb": round(agg["total_oz"] / 16, 2),
                "total_count": agg["total_count"],
                "slots": slots_sorted,
                "slot_badges": [
                    {"slot": s, "label": SLOT_LABELS.get(s, s), "color": SLOT_COLORS.get(s, SLOT_COLORS["other"])}
                    for s in slots_sorted
                ],
                "days": _day_breakdown_list(agg["by_day"]),
                "by_slot": {
                    s: {
                        "oz": round(v["oz"], 1),
                        "lb": round(v["oz"] / 16, 2),
                        "count": v["count"],
                        "days": _day_breakdown_list(v["by_day"]),
                    }
                    for s, v in agg["by_slot"].items()
                },
                "program_breakdown": [
                    {"name": v["name"], "oz": round(v["oz"], 1), "lb": round(v["oz"] / 16, 2), "count": v["count"]}
                    for v in sorted(agg["program_breakdown"].values(), key=lambda x: x["name"])
                ],
            })

        week_end = week_start + timedelta(days=6)
        weekly_output.append({
            "week_start": week_start,
            "week_end": week_end,
            "is_past": week_end < today,
            "ingredients": ingredients,
        })

    return weekly_output


def _day_breakdown_list(by_day: dict):
    """Turn a {date: {oz, count}} map into a sorted list of day summaries for display."""
    return [
        {
            "date": d.isoformat(),
            "label": d.strftime("%a"),
            "day_num": d.day,
            "oz": round(v["oz"], 1),
            "lb": round(v["oz"] / 16, 2),
            "count": v["count"],
        }
        for d, v in sorted(by_day.items())
    ]
