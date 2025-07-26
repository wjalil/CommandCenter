from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Tuple, Dict
from app.models.shift import Shift

def get_week_label(date: datetime) -> str:
    """Returns a 'Week of' label (e.g., 'Jul 22') for the Monday of that week."""
    start = date - timedelta(days=date.weekday())
    end = start + timedelta(days=6)     
    if start.month == end.month:
        return f"{start.strftime('%B %d')} – {end.strftime('%d')}"
    else:
        return f"{start.strftime('%b %d')} – {end.strftime('%b %d')}"

def compute_weekly_shifts_and_hours(
    shifts: List[Shift]
) -> Tuple[Dict[str, List[Shift]], Dict[str, Dict[str, float]]]:
    from collections import defaultdict
    from datetime import timedelta

    weekly_shifts_temp = defaultdict(list)
    weekly_hours_temp = defaultdict(lambda: defaultdict(float))

    for s in shifts:
        shift_date = s.start_time.date()  # ✅ Ensures grouping is based on actual shift day
        monday = shift_date - timedelta(days=shift_date.weekday())
        weekly_shifts_temp[monday].append(s)

        if s.assigned_worker_id:
            hours = (s.end_time - s.start_time).total_seconds() / 3600
            weekly_hours_temp[monday][s.assigned_worker_id] += round(hours, 2)

    weekly_shifts = {}
    weekly_hours = {}

    for monday in sorted(weekly_shifts_temp.keys()):
        end = monday + timedelta(days=6)

        # ✅ Include day names for clarity (e.g., Monday July 22 – Sunday July 28)
        if monday.month == end.month:
            label = f"{monday.strftime('%A %B %d')} – {end.strftime('%A %d')}"
        else:
            label = f"{monday.strftime('%a %b %d')} – {end.strftime('%a %b %d')}"

        weekly_shifts[label] = weekly_shifts_temp[monday]
        weekly_hours[label] = weekly_hours_temp[monday]

    return weekly_shifts, weekly_hours

