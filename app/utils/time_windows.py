from datetime import datetime, timedelta, timezone
from typing import Optional
import re

NY_TZ = timezone(timedelta(hours=-5))  # swap to your existing NY tz helper if you have one

def parse_since(since: Optional[str]) -> datetime:
    """
    Accepts '24h', '7d', '30d', 'YYYY-MM-DD', or None.
    Returns a UTC datetime lower bound.
    """
    now_utc = datetime.now(timezone.utc)
    if not since or since.strip().lower() in {"all", "any"}:
        # default: last 7d if caller wants a reasonable window
        return now_utc - timedelta(days=7)

    s = since.strip().lower()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        dt = datetime.fromisoformat(s).replace(tzinfo=NY_TZ)
        return dt.astimezone(timezone.utc)

    m = re.fullmatch(r"(\d+)([hdw])", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit == "h":
            return now_utc - timedelta(hours=n)
        if unit == "d":
            return now_utc - timedelta(days=n)
        if unit == "w":
            return now_utc - timedelta(weeks=n)

    return now_utc - timedelta(days=7)
