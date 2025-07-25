from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Tuple, Dict
from app.models.shift import Shift

def get_week_label(date: datetime) -> str:
    """Returns a 'Week of' label (e.g., 'Jul 22') for the Monday of that week."""
    start = date - timedelta(days=date.weekday())
    end = start + timedelta(days=6)     
    return f"{start.strftime('%B %d')} – {end.strftime('%d')}"

def compute_weekly_shifts_and_hours(
    shifts: List[Shift]
) -> Tuple[Dict[str, List[Shift]], Dict[str, Dict[str, float]]]:
    """
    Returns:
    - weekly_shifts: { "Jul 22": [shift1, shift2, ...] }
    - weekly_hours: { "Jul 22": {worker_id: hours, ...} }
    """
    weekly_shifts = defaultdict(list)
    weekly_hours = defaultdict(lambda: defaultdict(float))

    for s in shifts:
        week_label = get_week_label(s.date)
        weekly_shifts[week_label].append(s)

        if s.assigned_worker_id:
            hours = (s.end_time - s.start_time).total_seconds() / 3600
            weekly_hours[week_label][s.assigned_worker_id] += round(hours, 2)

    return dict(weekly_shifts), dict(weekly_hours)
