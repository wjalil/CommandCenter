"""
Friday Payroll

Pays everything *finished and unpaid* through the end of a pay week, in one
pay run:
  - closed time entries (hourly pay) whose shift started on or before payday
  - completed delivery routes (per-route driver pay) dated on or before payday
Anything earlier that slipped through (a missed clock-out fixed later, a route
completed late) is carried forward into the next run automatically; anything not
finished yet (still clocked in, route not completed) is flagged and rolls to the
following Friday. Every paid entry/route is stamped with its pay run, so nothing
is paid twice, and each worker gets a frozen pay stub to sign off on.
"""
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Iterable, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.delivery import DeliveryRoute
from app.models.payroll import PayRun, PayStub
from app.models.tenant import Tenant
from app.models.timeclock import TimeEntry, TimeStatus
from app.models.user import User
from app.utils.business_time import BusinessClock, PayWeek

PAYABLE_STATUSES = (TimeStatus.CLOSED, TimeStatus.APPROVED)
LONG_SHIFT_MINUTES = 12 * 60
PAYMENT_METHODS = ["Direct deposit", "Zelle", "Check", "Cash", "Other"]


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class PayItem:
    kind: str            # "shift" | "route"
    id: str
    work_date: date
    label: str
    minutes: int = 0
    rate: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    time_in: str = ""
    time_out: str = ""
    carried: bool = False
    flags: List[str] = field(default_factory=list)

    def as_line(self) -> dict:
        return {
            "kind": self.kind, "id": self.id, "date": self.work_date.isoformat(), "label": self.label,
            "minutes": self.minutes, "rate": str(self.rate), "amount": str(self.amount),
            "time_in": self.time_in, "time_out": self.time_out, "carried": self.carried,
        }


@dataclass
class WorkerPay:
    user_id: str
    name: str
    items: List[PayItem] = field(default_factory=list)

    @property
    def shifts(self) -> List[PayItem]:
        return [i for i in self.items if i.kind == "shift"]

    @property
    def routes(self) -> List[PayItem]:
        return [i for i in self.items if i.kind == "route"]

    @property
    def minutes(self) -> int:
        return sum(i.minutes for i in self.shifts)

    @property
    def hours(self) -> float:
        return round(self.minutes / 60, 2)

    @property
    def hourly(self) -> Decimal:
        return sum((i.amount for i in self.shifts), Decimal("0"))

    @property
    def route_pay(self) -> Decimal:
        return sum((i.amount for i in self.routes), Decimal("0"))

    @property
    def total(self) -> Decimal:
        return self.hourly + self.route_pay

    @property
    def flag_count(self) -> int:
        return sum(len(i.flags) for i in self.items)


@dataclass
class PayrollPreview:
    week: PayWeek
    floor: date
    workers: List[WorkerPay]
    still_open: List[str]        # warnings: people still clocked in
    pending_routes: List[str]    # warnings: routes this week not completed yet

    @property
    def total(self) -> Decimal:
        return sum((w.total for w in self.workers), Decimal("0"))

    @property
    def total_minutes(self) -> int:
        return sum(w.minutes for w in self.workers)

    @property
    def carried_count(self) -> int:
        return sum(1 for w in self.workers for i in w.items if i.carried)


async def payroll_floor(db: AsyncSession, tenant_id: int, clock: BusinessClock) -> date:
    """First day Friday Payroll looks at. Set once, the first time payroll is
    opened, to the start of that pay week — older unpaid-looking history was paid
    the old way and must not resurface as 'carried forward'."""
    tenant = await db.get(Tenant, tenant_id)
    if tenant.payroll_start_date is None:
        tenant.payroll_start_date = clock.pay_week().start
        await db.commit()
    return tenant.payroll_start_date


async def build_preview(db: AsyncSession, tenant_id: int, clock: BusinessClock, week: PayWeek,
                        user_ids: Optional[Iterable[str]] = None) -> PayrollPreview:
    floor = await payroll_floor(db, tenant_id, clock)
    user_ids = set(user_ids) if user_ids else None
    lo, _ = clock.utc_bounds(floor, floor)
    _, hi = clock.week_utc_bounds(week)
    week_lo, _ = clock.week_utc_bounds(week)

    users = {u.id: u for u in (await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars().all()}
    workers: Dict[str, WorkerPay] = {}

    def worker(uid: str) -> WorkerPay:
        if uid not in workers:
            u = users.get(uid)
            workers[uid] = WorkerPay(uid, (u.name if u and u.name else uid))
        return workers[uid]

    entries = (await db.execute(
        select(TimeEntry).where(and_(
            TimeEntry.tenant_id == tenant_id,
            TimeEntry.status.in_(PAYABLE_STATUSES),
            TimeEntry.pay_run_id.is_(None),
            TimeEntry.clock_in >= lo,
            TimeEntry.clock_in < hi,
        )).order_by(TimeEntry.clock_in)
    )).scalars().all()
    for e in entries:
        if user_ids is not None and e.user_id not in user_ids:
            continue
        u = users.get(e.user_id)
        minutes = int(e.duration_minutes or 0)
        rate = _money(e.hourly_rate if e.hourly_rate is not None else (u.hourly_rate if u else 0))
        amount = _money(e.gross_pay) if e.gross_pay is not None else _money(rate * Decimal(minutes) / 60)
        item = PayItem(
            kind="shift", id=e.id, work_date=clock.local_date(e.clock_in),
            label="Shift", minutes=minutes, rate=rate, amount=amount,
            time_in=clock.fmt_time(e.clock_in), time_out=clock.fmt_time(e.clock_out),
            carried=e.clock_in < week_lo,
        )
        if not rate:
            item.flags.append("No hourly rate set — pays $0")
        if "auto-closed" in (e.notes or ""):
            item.flags.append("Auto-closed (forgot to clock out?) — check the hours")
        elif minutes > LONG_SHIFT_MINUTES:
            item.flags.append(f"Long shift ({minutes // 60}h {minutes % 60}m)")
        worker(e.user_id).items.append(item)

    routes = (await db.execute(
        select(DeliveryRoute).where(and_(
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.status == "completed",
            DeliveryRoute.pay_run_id.is_(None),
            DeliveryRoute.assigned_driver_id.isnot(None),
            DeliveryRoute.date >= floor,
            DeliveryRoute.date <= week.end,
        )).order_by(DeliveryRoute.date)
    )).scalars().all()
    for r in routes:
        if user_ids is not None and r.assigned_driver_id not in user_ids:
            continue
        item = PayItem(
            kind="route", id=r.id, work_date=r.date, label=f"Route: {r.name}",
            rate=_money(r.driver_pay_rate), amount=_money(r.driver_pay_rate),
            carried=r.date < week.start,
        )
        if r.driver_pay_rate is None:
            item.flags.append("No route pay rate set — pays $0")
        worker(r.assigned_driver_id).items.append(item)

    # Not finished yet -> not paid this run; they roll to next Friday on their own
    still_open = []
    open_entries = (await db.execute(
        select(TimeEntry).where(
            TimeEntry.tenant_id == tenant_id, TimeEntry.status == TimeStatus.OPEN, TimeEntry.clock_in < hi,
        ).order_by(TimeEntry.clock_in)
    )).scalars().all()
    for e in open_entries:
        if user_ids is None or e.user_id in user_ids:
            name = users[e.user_id].name if e.user_id in users else e.user_id
            still_open.append(f"{name} is still clocked in (since {clock.fmt_datetime(e.clock_in)}) — that shift will be paid once they clock out.")

    pending_routes = []
    unfinished = (await db.execute(
        select(DeliveryRoute).where(
            DeliveryRoute.tenant_id == tenant_id,
            DeliveryRoute.assigned_driver_id.isnot(None),
            DeliveryRoute.status != "completed",
            DeliveryRoute.date >= max(floor, week.start),
            DeliveryRoute.date <= week.end,
        ).order_by(DeliveryRoute.date)
    )).scalars().all()
    for r in unfinished:
        if user_ids is None or r.assigned_driver_id in user_ids:
            name = users[r.assigned_driver_id].name if r.assigned_driver_id in users else "Driver"
            pending_routes.append(f"{name}: {r.name} ({r.date.strftime('%a %b')} {r.date.day}) isn't completed yet — paid once it's marked complete.")

    ordered = sorted(workers.values(), key=lambda w: w.name.lower())
    for w in ordered:
        w.items.sort(key=lambda i: (i.work_date, i.kind, i.time_in))
    return PayrollPreview(week, floor, ordered, still_open, pending_routes)


async def record_pay_run(db: AsyncSession, tenant_id: int, clock: BusinessClock, week: PayWeek, *,
                         paid_by_id: Optional[str], user_ids: Optional[Iterable[str]] = None,
                         payment_method: Optional[str] = None, notes: Optional[str] = None) -> Optional[PayRun]:
    """Pay everything in the preview: create the run, stamp every entry/route,
    and issue each worker a frozen pay stub. Returns None if nothing is payable."""
    preview = await build_preview(db, tenant_id, clock, week, user_ids)
    workers = [w for w in preview.workers if w.items]
    if not workers:
        return None

    run = PayRun(
        tenant_id=tenant_id, period_start=week.start, period_end=week.end, paid_at=datetime.utcnow(),
        paid_by_id=paid_by_id, payment_method=payment_method or None, notes=(notes or "").strip() or None,
        worker_count=len(workers), total_minutes=sum(w.minutes for w in workers),
        total_hourly=sum((w.hourly for w in workers), Decimal("0")),
        total_route_pay=sum((w.route_pay for w in workers), Decimal("0")),
        total_gross=sum((w.total for w in workers), Decimal("0")),
    )
    db.add(run)
    await db.flush()

    shift_ids = {i.id: i for w in workers for i in w.shifts}
    route_ids = {i.id for w in workers for i in w.routes}
    if shift_ids:
        for e in (await db.execute(select(TimeEntry).where(TimeEntry.id.in_(shift_ids)))).scalars().all():
            e.pay_run_id = run.id
            e.status = TimeStatus.PAID
            if e.gross_pay is None:  # e.g. auto-closed before rates were snapshotted
                e.hourly_rate = shift_ids[e.id].rate
                e.gross_pay = shift_ids[e.id].amount
    if route_ids:
        for r in (await db.execute(select(DeliveryRoute).where(DeliveryRoute.id.in_(route_ids)))).scalars().all():
            r.pay_run_id = run.id

    for w in workers:
        db.add(PayStub(
            tenant_id=tenant_id, pay_run_id=run.id, user_id=w.user_id, worker_name=w.name,
            period_start=week.start, period_end=week.end, minutes=w.minutes,
            hourly_gross=w.hourly, route_pay=w.route_pay, total_gross=w.total,
            lines_json=json.dumps([i.as_line() for i in w.items]),
        ))
    await db.commit()
    return run


async def void_pay_run(db: AsyncSession, run: PayRun) -> bool:
    """Undo a pay run recorded by mistake — only while no worker has signed for it."""
    stubs = (await db.execute(select(PayStub).where(PayStub.pay_run_id == run.id))).scalars().all()
    if any(s.status == "acknowledged" for s in stubs):
        return False
    for e in (await db.execute(select(TimeEntry).where(TimeEntry.pay_run_id == run.id))).scalars().all():
        e.pay_run_id = None
        e.status = TimeStatus.CLOSED
    for r in (await db.execute(select(DeliveryRoute).where(DeliveryRoute.pay_run_id == run.id))).scalars().all():
        r.pay_run_id = None
    await db.delete(run)
    await db.commit()
    return True


async def pay_runs(db: AsyncSession, tenant_id: int, limit: int = 12) -> List[PayRun]:
    return list((await db.execute(
        select(PayRun).where(PayRun.tenant_id == tenant_id)
        .options(selectinload(PayRun.stubs), selectinload(PayRun.paid_by))
        .order_by(PayRun.paid_at.desc()).limit(limit)
    )).scalars().all())


async def worker_stubs(db: AsyncSession, tenant_id: int, user_id: str, limit: int = 26) -> List[PayStub]:
    return list((await db.execute(
        select(PayStub).where(PayStub.tenant_id == tenant_id, PayStub.user_id == user_id)
        .options(selectinload(PayStub.pay_run))
        .order_by(PayStub.created_at.desc()).limit(limit)
    )).scalars().all())


async def unsigned_stubs(db: AsyncSession, tenant_id: int, user_id: str) -> List[PayStub]:
    return list((await db.execute(
        select(PayStub).where(PayStub.tenant_id == tenant_id, PayStub.user_id == user_id, PayStub.status == "issued")
        .order_by(PayStub.created_at.desc())
    )).scalars().all())
