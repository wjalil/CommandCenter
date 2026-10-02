"""
Business Time

The one place that knows what time it is *for the business*. Timestamps are
stored as naive UTC (TimeEntry.clock_in etc.); everything a person sees or picks
— "today", a pay week, 9:05 AM — is in the tenant's own timezone. Every
conversion goes through here so no screen has to guess.

Pay weeks end on payday: with Friday payroll the week runs Saturday 00:00 →
Friday 23:59 local, so Sunday prep for Monday's food is paid the same Friday as
the Mon–Fri deliveries it was made for. A shift belongs to the day (and pay
week) it *started* in, even if it runs past midnight.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_TZ = "America/New_York"
DEFAULT_PAY_WEEK_END = 4  # Friday (Monday=0 … Sunday=6)
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _clean_time(text: str) -> str:
    return text.lstrip("0") or "0"


@dataclass(frozen=True)
class PayWeek:
    start: date        # first day (e.g. Saturday)
    end: date          # last day, inclusive — payday (e.g. Friday)

    @property
    def end_exclusive(self) -> date:
        return self.end + timedelta(days=1)

    @property
    def payday(self) -> date:
        return self.end

    @property
    def label(self) -> str:
        return f"{self.start.strftime('%a %b')} {self.start.day} – {self.end.strftime('%a %b')} {self.end.day}"

    @property
    def payday_label(self) -> str:
        return f"{self.end.strftime('%a %b')} {self.end.day}"

    def shifted(self, weeks: int) -> "PayWeek":
        delta = timedelta(days=7 * weeks)
        return PayWeek(self.start + delta, self.end + delta)

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end


@dataclass(frozen=True)
class BusinessClock:
    tz_name: str = DEFAULT_TZ
    pay_week_end: int = DEFAULT_PAY_WEEK_END

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    # ---- now / today ----
    def now(self) -> datetime:
        return datetime.now(self.tz)

    def today(self) -> date:
        return self.now().date()

    # ---- conversions ----
    def local(self, utc_naive: Optional[datetime]) -> Optional[datetime]:
        """Stored naive-UTC timestamp -> aware local time. Never depends on the server's own timezone."""
        if utc_naive is None:
            return None
        if utc_naive.tzinfo is None:
            utc_naive = utc_naive.replace(tzinfo=timezone.utc)
        return utc_naive.astimezone(self.tz)

    def local_date(self, utc_naive: Optional[datetime]) -> Optional[date]:
        loc = self.local(utc_naive)
        return loc.date() if loc else None

    def to_utc_naive(self, local_wall: datetime) -> datetime:
        """A wall-clock time typed by a person (e.g. a datetime-local input) -> naive UTC for storage."""
        if local_wall.tzinfo is None:
            local_wall = local_wall.replace(tzinfo=self.tz)
        return local_wall.astimezone(timezone.utc).replace(tzinfo=None)

    def parse_local_input(self, text: Optional[str]) -> Optional[datetime]:
        """'YYYY-MM-DDTHH:MM' from a datetime-local input -> naive UTC."""
        if not text:
            return None
        return self.to_utc_naive(datetime.fromisoformat(text.strip().replace("Z", "")))

    def to_local_input(self, utc_naive: Optional[datetime]) -> str:
        loc = self.local(utc_naive)
        return loc.strftime("%Y-%m-%dT%H:%M") if loc else ""

    def utc_bounds(self, start: date, end_exclusive: date) -> Tuple[datetime, datetime]:
        """Local calendar days [start, end_exclusive) -> naive-UTC [lo, hi) for filtering stored timestamps."""
        lo = datetime(start.year, start.month, start.day, tzinfo=self.tz)
        hi = datetime(end_exclusive.year, end_exclusive.month, end_exclusive.day, tzinfo=self.tz)
        return lo.astimezone(timezone.utc).replace(tzinfo=None), hi.astimezone(timezone.utc).replace(tzinfo=None)

    # ---- pay weeks ----
    def pay_week(self, d: Optional[date] = None) -> PayWeek:
        """The pay week containing local date d (default: today)."""
        d = d or self.today()
        days_to_end = (self.pay_week_end - d.weekday()) % 7
        end = d + timedelta(days=days_to_end)
        return PayWeek(end - timedelta(days=6), end)

    def week_utc_bounds(self, week: PayWeek) -> Tuple[datetime, datetime]:
        return self.utc_bounds(week.start, week.end_exclusive)

    # ---- display ----
    def fmt_time(self, utc_naive: Optional[datetime]) -> str:
        loc = self.local(utc_naive)
        return _clean_time(loc.strftime("%I:%M %p")) if loc else "—"

    def fmt_date(self, utc_naive: Optional[datetime]) -> str:
        loc = self.local(utc_naive)
        return f"{loc.strftime('%a %b')} {loc.day}" if loc else "—"

    def fmt_datetime(self, utc_naive: Optional[datetime]) -> str:
        loc = self.local(utc_naive)
        return f"{self.fmt_date(utc_naive)}, {self.fmt_time(utc_naive)}" if loc else "—"

    @property
    def tz_abbrev(self) -> str:
        return self.now().strftime("%Z")

    @property
    def pay_week_end_name(self) -> str:
        return WEEKDAYS[self.pay_week_end]


def valid_tz(name: Optional[str]) -> bool:
    try:
        ZoneInfo(name or "")
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def clock_for_tenant(tenant) -> BusinessClock:
    tz_name = getattr(tenant, "timezone", None) or DEFAULT_TZ
    end = getattr(tenant, "pay_week_end_weekday", None)
    return BusinessClock(
        tz_name=tz_name if valid_tz(tz_name) else DEFAULT_TZ,
        pay_week_end=end if end is not None and 0 <= end <= 6 else DEFAULT_PAY_WEEK_END,
    )


async def get_business_clock(db: AsyncSession, tenant_id: int) -> BusinessClock:
    from app.models.tenant import Tenant
    return clock_for_tenant(await db.get(Tenant, tenant_id))


def parse_week_param(clock: BusinessClock, value: Optional[str]) -> PayWeek:
    """?week=YYYY-MM-DD (any day in the week) -> that pay week; bad/missing -> this week."""
    if value:
        try:
            return clock.pay_week(date.fromisoformat(value[:10]))
        except ValueError:
            pass
    return clock.pay_week()
