from collections import defaultdict
from datetime import timedelta, date
from sqlalchemy.orm import Session
from sqlalchemy import and_
from calendar import monthrange

from app.models.catering import CateringMenuDay, CateringMonthlyMenu


def build_weekly_ingredient_list(
    db: Session,
    monthly_menu_id: str
):
    """
    Returns a list of weeks with ingredients grouped by meal slot for a single menu.
    """
    menu_days = (
        db.query(CateringMenuDay)
        .filter(CateringMenuDay.monthly_menu_id == monthly_menu_id)
        .order_by(CateringMenuDay.service_date)
        .all()
    )

    return _process_menu_days_to_weeks(menu_days)


def build_aggregate_ingredient_list(
    db: Session,
    tenant_id: int,
    year: int,
    month: int,
    program_id: str = None
):
    """
    Returns aggregated weekly ingredient list across all programs (or filtered by one).

    Args:
        db: Database session
        tenant_id: Tenant ID
        year: Year to filter
        month: Month to filter
        program_id: Optional - filter to specific program

    Returns:
        {
            "weeks": [...],
            "programs": [list of programs included],
            "total_ingredients": int
        }
    """
    # Build date range for the month
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])

    # Query all menu days in the date range
    query = (
        db.query(CateringMenuDay)
        .join(CateringMonthlyMenu)
        .filter(
            CateringMonthlyMenu.tenant_id == tenant_id,
            CateringMenuDay.service_date >= first_day,
            CateringMenuDay.service_date <= last_day
        )
    )

    if program_id:
        query = query.filter(CateringMonthlyMenu.program_id == program_id)

    menu_days = query.order_by(CateringMenuDay.service_date).all()

    # Get unique programs
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

    # Count total unique ingredients
    all_ingredients = set()
    for week in weeks:
        all_ingredients.update(week["ingredients"])

    return {
        "weeks": weeks,
        "programs": list(programs_seen.values()),
        "total_ingredients": len(all_ingredients)
    }


def _process_menu_days_to_weeks(menu_days):
    """
    Process menu days into weekly ingredient structure.
    """
    weeks = defaultdict(lambda: {
        "all": set(),
        "breakfast": set(),
        "lunch": set(),
        "snack": set()
    })

    for day in menu_days:
        # Monday-based week
        week_start = day.service_date - timedelta(days=day.service_date.weekday())

        for component in day.components:
            if component.food_component:
                name = component.food_component.name
                slot = component.meal_slot

                weeks[week_start]["all"].add(name)
                if slot in weeks[week_start]:
                    weeks[week_start][slot].add(name)

    weekly_output = []

    for week_start in sorted(weeks.keys()):
        week_data = weeks[week_start]
        weekly_output.append({
            "week_start": week_start,
            "week_end": week_start + timedelta(days=6),
            "ingredients": sorted(week_data["all"]),
            "by_meal": {
                "breakfast": sorted(week_data["breakfast"]),
                "lunch": sorted(week_data["lunch"]),
                "snack": sorted(week_data["snack"]),
            }
        })

    return weekly_output
