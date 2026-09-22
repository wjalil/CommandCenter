import json
from collections import defaultdict
from datetime import timedelta, date
from sqlalchemy.orm import Session, joinedload

from app.models.catering import CateringMenuDay, CateringMonthlyMenu, MenuDayComponent, FoodComponent

SLOT_LABELS = {
    "breakfast": "B",
    "lunch": "L",
    "snack": "S",
    "am_snack": "AM",
    "pm_snack": "PM",
}
SLOT_NAMES = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "snack": "Snack",
    "am_snack": "AM Snack",
    "pm_snack": "PM Snack",
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
UNCATEGORIZED = "Other"
CATEGORY_COLORS = ["#4C6EF5", "#12B886", "#FD7E14", "#7048E8", "#F5A623", "#E64980", "#15AABF", "#82C91E"]


def _category_color(name):
    """Deterministic color per CACFP food-group name, independent of hash randomization."""
    return CATEGORY_COLORS[sum(ord(c) for c in name) % len(CATEGORY_COLORS)]


def build_range_ingredient_list(
    db: Session,
    tenant_id: int,
    start_date: date,
    end_date: date,
    program_id: str = None
):
    """
    Returns the shopping list for an arbitrary date range (not clipped to
    week/month boundaries), pre-grouped three ways so the page can offer
    Category / Day / Program views without re-querying:

        {
            "ingredients": [...flat list, checkable...],
            "by_category": [{"name": CACFP food group, "ingredients": [...]}],
            "by_day": [{"date", "weekday", ..., "ingredients": [...]}],
            "by_program": [{"name": program name, "ingredients": [...]}],
            "programs": [list of programs included],
            "total_ingredients": int
        }
    """
    menu_days, programs_seen = _fetch_menu_days(db, tenant_id, start_date, end_date, program_id)
    ingredients = _format_ingredients(_aggregate_ingredients(menu_days))

    return {
        "ingredients": ingredients,
        "by_category": _group_by_category(ingredients),
        "by_day": _group_by_day(ingredients, start_date, end_date),
        "by_program": _group_by_program(ingredients),
        "programs": list(programs_seen.values()),
        "total_ingredients": len(ingredients),
    }


def _fetch_menu_days(db: Session, tenant_id: int, first_day: date, last_day: date, program_id: str = None):
    query = (
        db.query(CateringMenuDay)
        .join(CateringMonthlyMenu)
        .options(
            joinedload(CateringMenuDay.components)
            .joinedload(MenuDayComponent.food_component)
            .joinedload(FoodComponent.component_type),
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

    return menu_days, programs_seen


def _new_day_bucket():
    return {"oz": 0.0, "count": 0}


def _new_slot_bucket():
    return {"oz": 0.0, "count": 0, "by_day": defaultdict(_new_day_bucket)}


def _new_program_bucket():
    return {"name": None, "oz": 0.0, "count": 0, "by_slot": defaultdict(_new_day_bucket)}


def _new_ingredient_bucket():
    return {
        "total_oz": 0.0,
        "total_count": 0,
        "slots": set(),
        "by_slot": defaultdict(_new_slot_bucket),
        "by_day": defaultdict(_new_day_bucket),
        "program_breakdown": defaultdict(_new_program_bucket),
        "category": UNCATEGORIZED,
        "category_sort_order": 999,
    }


def _aggregate_ingredients(menu_days):
    """
    Aggregate real quantities (oz/lb) needed per ingredient across a set of
    menu days, with per-meal-slot, per-day and per-program breakdowns (and
    the per-program breakdown further split by slot) for each ingredient.
    Works for any set of days — a single day or a multi-week custom range.
    """
    ingredients = defaultdict(_new_ingredient_bucket)

    for day in menu_days:
        program = day.monthly_menu.program if day.monthly_menu else None
        if not program:
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

            agg = ingredients[name]
            agg["total_oz"] += total_oz
            agg["total_count"] += meal_count
            agg["slots"].add(slot)

            component_type = component.food_component.component_type
            if component_type:
                agg["category"] = component_type.name
                agg["category_sort_order"] = component_type.sort_order

            by_slot = agg["by_slot"][slot]
            by_slot["oz"] += total_oz
            by_slot["count"] += meal_count
            by_slot["by_day"][day.service_date]["oz"] += total_oz
            by_slot["by_day"][day.service_date]["count"] += meal_count

            agg["by_day"][day.service_date]["oz"] += total_oz
            agg["by_day"][day.service_date]["count"] += meal_count

            pb = agg["program_breakdown"][program.id]
            pb["name"] = program.name
            pb["oz"] += total_oz
            pb["count"] += meal_count
            pb_slot = pb["by_slot"][slot]
            pb_slot["oz"] += total_oz
            pb_slot["count"] += meal_count

    return ingredients


def _slot_filter_dict(total_oz, total_count, by_slot_source):
    """Build the {"all": {...}, "<slot>": {...}} map the meal-slot filter
    reads client-side, from a total plus a {slot: {oz, count}}-shaped source."""
    out = {"all": {"oz": round(total_oz, 1), "lb": round(total_oz / 16, 2), "count": total_count}}
    for slot, v in by_slot_source.items():
        out[slot] = {"oz": round(v["oz"], 1), "lb": round(v["oz"] / 16, 2), "count": v["count"]}
    return out


def _format_ingredients(ingredients_agg):
    ingredients = []
    for name, agg in sorted(ingredients_agg.items()):
        slots_sorted = sorted(agg["slots"], key=lambda s: SLOT_ORDER.index(s) if s in SLOT_ORDER else 99)
        ingredients.append({
            "name": name,
            "category": agg["category"],
            "category_sort_order": agg["category_sort_order"],
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
            "slot_filter": _slot_filter_dict(agg["total_oz"], agg["total_count"], agg["by_slot"]),
            "program_breakdown": [
                {
                    "name": v["name"],
                    "oz": round(v["oz"], 1),
                    "lb": round(v["oz"] / 16, 2),
                    "count": v["count"],
                    "slot_filter": _slot_filter_dict(v["oz"], v["count"], v["by_slot"]),
                }
                for v in sorted(agg["program_breakdown"].values(), key=lambda x: x["name"])
            ],
        })
    return ingredients


def _group_by_category(ingredients):
    """Group into CACFP food-group sections (Meat/Meat Alternate, Grains, Vegetables, ...) —
    the closest thing this data has to a grocery aisle, so shopping matches how you'd
    actually walk the store."""
    groups = defaultdict(list)
    sort_orders = {}
    for ing in ingredients:
        groups[ing["category"]].append(ing)
        sort_orders[ing["category"]] = ing["category_sort_order"]

    return [
        {"name": cat, "color": _category_color(cat), "ingredients": items}
        for cat, items in sorted(groups.items(), key=lambda kv: (sort_orders[kv[0]], kv[0]))
    ]


def _group_by_day(ingredients, start_date, end_date):
    """Same range, sectioned by calendar day — a pull sheet for ordering or
    prepping just part of the range instead of all of it at once."""
    by_date = {}
    d = start_date
    while d <= end_date:
        by_date[d] = {}
        d += timedelta(days=1)

    for ing in ingredients:
        slot_by_date = defaultdict(dict)
        for slot, sv in ing["by_slot"].items():
            for day in sv["days"]:
                slot_by_date[date.fromisoformat(day["date"])][slot] = day

        for day in ing["days"]:
            d = date.fromisoformat(day["date"])
            slot_filter = {"all": {"oz": day["oz"], "lb": day["lb"], "count": day["count"]}}
            for slot, sv in slot_by_date.get(d, {}).items():
                slot_filter[slot] = {"oz": sv["oz"], "lb": sv["lb"], "count": sv["count"]}
            by_date.setdefault(d, {})[ing["name"]] = {
                "name": ing["name"],
                "category": ing["category"],
                "oz": day["oz"],
                "lb": day["lb"],
                "count": day["count"],
                "slot_badges": [b for b in ing["slot_badges"] if b["slot"] in slot_filter],
                "slot_filter": slot_filter,
            }

    today = date.today()
    return [
        {
            "date": d.isoformat(),
            "weekday": d.strftime("%A"),
            "short_weekday": d.strftime("%a"),
            "day_num": d.day,
            "month_label": d.strftime("%b"),
            "is_today": d == today,
            "is_past": d < today,
            "ingredients": sorted(items.values(), key=lambda i: i["name"]),
        }
        for d, items in sorted(by_date.items())
    ]


def _group_by_program(ingredients):
    """Same range, sectioned by which program/client needs it — useful for
    splitting an order or checking client-specific billing."""
    by_program = defaultdict(list)
    for ing in ingredients:
        for pb in ing["program_breakdown"]:
            by_program[pb["name"]].append({
                "name": ing["name"],
                "category": ing["category"],
                "oz": pb["oz"],
                "lb": pb["lb"],
                "count": pb["count"],
                "slot_badges": [b for b in ing["slot_badges"] if b["slot"] in pb["slot_filter"]],
                "slot_filter": pb["slot_filter"],
            })

    return [
        {"name": prog_name, "ingredients": sorted(items, key=lambda i: i["name"])}
        for prog_name, items in sorted(by_program.items())
    ]


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
