# app/utils/timezones.py
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from typing import Optional

NY  = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

def monday_of_week_local(d: date) -> datetime:
    # Monday=0 .. Sunday=6
    monday = d - timedelta(days=d.weekday())
    return datetime(monday.year, monday.month, monday.day, 0, 0, 0, tzinfo=NY)

def week_bounds_utc_for_date(d: date):
    """Mon 00:00 -> next Mon 00:00 in NY, returned as UTC-aware datetimes."""
    start_local = monday_of_week_local(d)
    end_local   = start_local + timedelta(days=7)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)

def current_week_bounds_utc(now: Optional[datetime] = None):
    local_now = (now or datetime.now(NY)).astimezone(NY)
    return week_bounds_utc_for_date(local_now.date())

def ui_week_bounds_utc(week_start_str: Optional[str] = None, week_end_str: Optional[str] = None):
    """
    Unifies all callers:
    - If both dates are provided: treat them as *local NY dates* coming from a picker.
      We build a half-open window [start_local 00:00, end_local 00:00).
    - If only week_start provided: interpret it as "any date in target week" (NY),
      and return that Monday->Monday.
    - If neither provided: use current Monday->Monday.
    Returns (start_utc, end_utc, start_local, end_local) to help you label the UI.
    """
    if week_start_str and week_end_str:
        sd = date.fromisoformat(week_start_str)
        ed = date.fromisoformat(week_end_str)
        start_local = datetime(sd.year, sd.month, sd.day, 0, 0, 0, tzinfo=NY)
        end_local   = datetime(ed.year, ed.month, ed.day, 0, 0, 0, tzinfo=NY)
        return (start_local.astimezone(UTC),
                end_local.astimezone(UTC),
                start_local,
                end_local)

    if week_start_str:
        sd = date.fromisoformat(week_start_str)  # interpret as "a date in the week"
        start_utc, end_utc = week_bounds_utc_for_date(sd)
        start_local = start_utc.astimezone(NY)
        end_local   = end_utc.astimezone(NY)
        return start_utc, end_utc, start_local, end_local

    # default: this week
    start_utc, end_utc = current_week_bounds_utc()
    start_local = start_utc.astimezone(NY)
    end_local   = end_utc.astimezone(NY)
    return start_utc, end_utc, start_local, end_local
