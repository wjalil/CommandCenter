"""
Time clock business time + Friday Payroll + pay stub sign-off — end-to-end tests.

In-memory SQLite, real endpoint functions, real templates. No server, no pytest:

    .venv\\Scripts\\python.exe tests\\test_timeclock_payroll.py
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import asyncio
import json
import traceback
import warnings
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import unquote, urlencode
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import app.models  # noqa: F401
from app.models.base import Base
from app.models.tenant import Tenant
from app.models.user import User
from app.models.timeclock import TimeEntry, TimeStatus
from app.models.payroll import PayRun, PayStub
from app.models.delivery import DeliveryRoute
from app.utils.business_time import BusinessClock, PayWeek
from app.utils import timeclock_service
from app.services import payroll as payroll_svc
from app.api import payroll_routes as payr
from app.api import worker_routes as wr
from app.api.admin import admin_timeclock_routes as atr

warnings.filterwarnings("ignore")

TENANT_ID = 1
NY = ZoneInfo("America/New_York")
CLOCK = BusinessClock()
WEEK = CLOCK.pay_week()            # the real current pay week (Sat..Fri)
SUNDAY = WEEK.start + timedelta(days=1)
MONDAY = WEEK.start + timedelta(days=2)


def utc(d: date, hh: int, mm: int = 0) -> datetime:
    """Local NY wall time on day d -> naive UTC, as stored."""
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=NY).astimezone(timezone.utc).replace(tzinfo=None)


def make_request(form=None, query=None, method="POST", ip="203.0.113.7"):
    payload = urlencode(form or {}, doseq=True).encode()
    scope = {
        "type": "http", "method": method, "path": "/", "client": (ip, 5555),
        "headers": [(b"content-type", b"application/x-www-form-urlencoded"), (b"user-agent", b"TestPhone/1.0")],
        "query_string": urlencode(query or {}).encode(), "session": {}, "state": {},
    }

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    req = Request(scope, receive)
    req.state.tenant_id = TENANT_ID
    return req


def html(resp) -> str:
    return resp.body.decode("utf-8")


def location(resp) -> str:
    return unquote(resp.headers["location"])


class Env:
    async def setup(self):
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.Session() as db:
            db.add(Tenant(id=TENANT_ID, name="Test Kitchen", slug="test-kitchen",
                          payroll_start_date=WEEK.start - timedelta(days=21)))
            self.admin = User(name="Owner", pin_code="1000", role="admin", tenant_id=TENANT_ID, is_active=True)
            self.cook = User(name="Ana Cook", pin_code="2000", role="worker", tenant_id=TENANT_ID, is_active=True,
                             hourly_rate=Decimal("20.00"))
            self.driver = User(name="Dan Driver", pin_code="3000", role="worker", worker_type="Driver",
                               tenant_id=TENANT_ID, is_active=True)
            self.other = User(name="Olu Other", pin_code="4000", role="worker", tenant_id=TENANT_ID, is_active=True,
                              hourly_rate=Decimal("18.00"))
            db.add_all([self.admin, self.cook, self.driver, self.other])
            await db.commit()
        return self

    async def close(self):
        await self.engine.dispose()

    async def shift(self, user, start: datetime, minutes: int, status=TimeStatus.CLOSED, notes=None):
        async with self.Session() as db:
            rate = float(user.hourly_rate or 0)
            e = TimeEntry(
                id=f"e{start.isoformat()}{user.id}", tenant_id=TENANT_ID, user_id=user.id, clock_in=start,
                clock_out=None if status == TimeStatus.OPEN else start + timedelta(minutes=minutes),
                status=status, notes=notes,
                duration_minutes=None if status == TimeStatus.OPEN else minutes,
                hourly_rate=rate, gross_pay=None if status == TimeStatus.OPEN else round(minutes / 60 * rate, 2),
            )
            db.add(e)
            await db.commit()
            return e.id

    async def route(self, d: date, pay, status="completed", name="R1"):
        async with self.Session() as db:
            r = DeliveryRoute(name=name, date=d, assigned_driver_id=self.driver.id, status=status,
                              tenant_id=TENANT_ID, driver_pay_rate=pay)
            db.add(r)
            await db.commit()
            return r.id

    async def preview(self, week=WEEK):
        async with self.Session() as db:
            return await payroll_svc.build_preview(db, TENANT_ID, CLOCK, week)

    async def pay(self, week=WEEK, user_ids=None):
        async with self.Session() as db:
            pv = await payroll_svc.build_preview(db, TENANT_ID, CLOCK, week)
            ids = user_ids or [w.user_id for w in pv.workers]
            resp = await payr.admin_payroll_run(
                make_request(form={"week": week.start.isoformat(), "user_ids": ids, "payment_method": "Zelle"}),
                db=db, user=self.admin)
            return resp

    async def stub_for(self, user):
        async with self.Session() as db:
            return (await db.execute(select(PayStub).where(PayStub.user_id == user.id)
                                     .order_by(PayStub.created_at.desc()))).scalars().first()


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


async def with_env(fn):
    env = await Env().setup()
    try:
        await fn(env)
    finally:
        await env.close()


# ==================== business time ====================

@test
async def test_pay_week_runs_saturday_to_friday(env):
    clock = BusinessClock()
    thursday = date(2026, 10, 1)
    week = clock.pay_week(thursday)
    assert (week.start, week.end) == (date(2026, 9, 26), date(2026, 10, 2))
    assert week.start.weekday() == 5 and week.end.weekday() == 4, "Sat..Fri, payday Friday"
    assert clock.pay_week(date(2026, 9, 27)) == week, "Sunday prep belongs to the coming Friday's pay"
    assert clock.pay_week(date(2026, 10, 2)) == week, "payday itself is in the week"
    assert clock.pay_week(date(2026, 10, 3)).start == date(2026, 10, 3), "Saturday starts the next week"
    assert week.label == "Sat Sep 26 – Fri Oct 2" and week.payday_label == "Fri Oct 2"


@test
async def test_times_never_depend_on_server_timezone(env):
    stored = datetime(2026, 10, 1, 21, 15)  # naive UTC = 5:15 PM EDT
    assert CLOCK.fmt_time(stored) == "5:15 PM"
    assert CLOCK.local(stored).utcoffset() == timedelta(hours=-4)
    assert CLOCK.parse_local_input("2026-10-01T17:15") == stored
    assert CLOCK.to_local_input(stored) == "2026-10-01T17:15"
    winter = datetime(2026, 12, 1, 22, 15)
    assert CLOCK.fmt_time(winter) == "5:15 PM", "EST after daylight saving ends"


@test
async def test_week_bounds_across_daylight_saving_change(env):
    week = CLOCK.pay_week(date(2026, 11, 1))  # DST ends Sun Nov 1, 2026
    lo, hi = CLOCK.week_utc_bounds(week)
    assert lo == datetime(2026, 10, 31, 4, 0), "Sat 00:00 EDT"
    assert hi == datetime(2026, 11, 7, 5, 0), "next Sat 00:00 EST"


# ==================== payroll ====================

@test
async def test_sunday_night_shift_is_in_this_pay_week(env):
    # Sunday 9 PM ET = Monday 01:00 UTC — the old UTC-date filter put this in the wrong week
    await env.shift(env.cook, utc(SUNDAY, 21), 180)
    pv = await env.preview()
    ana = next(w for w in pv.workers if w.name == "Ana Cook")
    assert ana.items[0].work_date == SUNDAY and not ana.items[0].carried
    async with env.Session() as db:
        page = html(await wr.worker_timeclock_history(make_request(method="GET"), db=db, user=env.cook, week=None))
    assert "9:00 PM" in page and "12:00 AM" in page, "server-rendered in business time"


@test
async def test_preview_totals_flags_and_unfinished_work(env):
    await env.shift(env.cook, utc(SUNDAY, 9), 300)            # Sunday prep 5h
    await env.shift(env.cook, utc(MONDAY, 8), 240)            # Monday 4h
    await env.route(MONDAY, 50)                               # completed route
    await env.route(WEEK.end, 50, status="assigned", name="Fri AM")  # not done yet
    await env.shift(env.other, utc(MONDAY, 7), 0, status=TimeStatus.OPEN)
    await env.shift(env.other, utc(MONDAY - timedelta(days=30), 7), 60)  # before payroll started -> ignored

    pv = await env.preview()
    by_name = {w.name: w for w in pv.workers}
    assert by_name["Ana Cook"].total == Decimal("180.00") and by_name["Ana Cook"].hours == 9.0
    assert by_name["Dan Driver"].route_pay == Decimal("50.00")
    assert "Olu Other" not in by_name, "still clocked in -> nothing to pay yet; old shift predates payroll"
    assert any("still clocked in" in w for w in pv.still_open)
    assert any("Fri AM" in w for w in pv.pending_routes)
    assert pv.total == Decimal("230.00")


@test
async def test_pay_run_stamps_everything_and_never_pays_twice(env):
    e1 = await env.shift(env.cook, utc(MONDAY, 8), 240)
    r1 = await env.route(MONDAY, 50)
    resp = await env.pay()
    assert "/admin/payroll/runs/" in location(resp), location(resp)

    async with env.Session() as db:
        entry = await db.get(TimeEntry, e1)
        route = await db.get(DeliveryRoute, r1)
        run = (await db.execute(select(PayRun))).scalar_one()
        assert entry.status == TimeStatus.PAID and entry.pay_run_id == run.id
        assert route.pay_run_id == run.id
        assert run.total_gross == Decimal("130.00") and run.worker_count == 2 and run.payment_method == "Zelle"
        stubs = (await db.execute(select(PayStub))).scalars().all()
    assert {s.worker_name for s in stubs} == {"Ana Cook", "Dan Driver"}
    assert all(s.status == "issued" for s in stubs)

    assert (await env.preview()).workers == []
    again = await env.pay(user_ids=[env.cook.id])
    assert "Nothing left to pay" in location(again)


@test
async def test_late_fix_carries_forward_to_next_payroll(env):
    last_week = WEEK.shifted(-1)
    await env.pay(week=last_week)  # nothing yet
    # A missed shift from last week gets entered after last Friday's payroll
    await env.shift(env.cook, utc(last_week.start + timedelta(days=3), 8), 120)
    pv = await env.preview()
    item = pv.workers[0].items[0]
    assert item.carried is True and pv.carried_count == 1
    await env.pay()
    stub = await env.stub_for(env.cook)
    assert stub.lines[0]["carried"] is True and stub.total_gross == Decimal("40.00")


@test
async def test_paid_entries_cannot_be_edited_or_deleted(env):
    e1 = await env.shift(env.cook, utc(MONDAY, 8), 240)
    await env.pay()
    async with env.Session() as db:
        resp = await atr.admin_timeclock_edit_entry(
            entry_id=e1, db=db, user=env.admin, clock_in=f"{MONDAY.isoformat()}T07:00", clock_out=None,
            notes=None, edit_reason=None, start=WEEK.start.isoformat(), end=WEEK.end_exclusive.isoformat())
        assert "Cannot+edit+PAID" in resp.headers["location"]
        resp = await atr.admin_timeclock_delete_entry(entry_id=e1, db=db, user=env.admin)
        assert resp.status_code == 400


# ==================== pay stubs + sign-off ====================

@test
async def test_worker_signs_for_pay_with_audit_trail(env):
    await env.shift(env.cook, utc(MONDAY, 8), 240)
    await env.pay()
    stub = await env.stub_for(env.cook)

    async with env.Session() as db:
        home = html(await wr.worker_home(make_request(method="GET"), db=db, user=env.cook))
        assert "You got paid</span> $80.00" in home and f"/worker/pay/{stub.id}" in home

        page = html(await payr.worker_pay_stub(make_request(method="GET"), stub_id=stub.id, db=db, user=env.cook))
        assert "Sign for your pay" in page and "$80.00" in page and "Zelle" in page

        resp = await payr.worker_acknowledge(make_request(), stub_id=stub.id, signature_name="Ana Cook", confirm=None,
                                             db=db, user=env.cook)
        assert "tick the box" in location(resp), "must confirm the amount"
        await payr.worker_acknowledge(make_request(), stub_id=stub.id, signature_name="Ana Cook", confirm="1",
                                      db=db, user=env.cook)

    stub = await env.stub_for(env.cook)
    assert stub.status == "acknowledged" and stub.signature_name == "Ana Cook"
    assert stub.ack_ip == "203.0.113.7" and stub.ack_user_agent == "TestPhone/1.0" and stub.acknowledged_at

    async with env.Session() as db:
        home = html(await wr.worker_home(make_request(method="GET"), db=db, user=env.cook))
        assert "You got paid" not in home, "nothing left to sign"
        run_page = html(await payr.admin_payroll_run_detail(make_request(method="GET"), run_id=stub.pay_run_id,
                                                            db=db, user=env.admin))
        assert "Signed “Ana Cook”" in run_page and "203.0.113.7" in run_page
        assert "Void this pay run" not in run_page, "can't void once someone signed"


@test
async def test_dispute_then_resolve_then_sign(env):
    await env.shift(env.cook, utc(MONDAY, 8), 240)
    await env.pay()
    stub = await env.stub_for(env.cook)
    async with env.Session() as db:
        await payr.worker_dispute(stub_id=stub.id, dispute_note="Missing my Sunday prep shift", db=db, user=env.cook)
    stub = await env.stub_for(env.cook)
    assert stub.status == "disputed" and "Sunday" in stub.dispute_note
    async with env.Session() as db:
        run_page = html(await payr.admin_payroll_run_detail(make_request(method="GET"), run_id=stub.pay_run_id,
                                                            db=db, user=env.admin))
        assert "Problem reported" in run_page and "Missing my Sunday prep shift" in run_page
        await payr.admin_resolve_dispute(stub_id=stub.id, resolution_note="Added to next Friday", db=db, user=env.admin)
    stub = await env.stub_for(env.cook)
    assert stub.status == "issued" and stub.resolution_note == "Added to next Friday"


@test
async def test_workers_only_see_their_own_stubs(env):
    await env.shift(env.cook, utc(MONDAY, 8), 240)
    await env.pay()
    stub = await env.stub_for(env.cook)
    async with env.Session() as db:
        resp = await payr.worker_pay_stub(make_request(method="GET"), stub_id=stub.id, db=db, user=env.other)
        assert resp.status_code == 303 and resp.headers["location"] == "/worker/pay"
        await payr.worker_acknowledge(make_request(), stub_id=stub.id, signature_name="Olu", confirm="1",
                                      db=db, user=env.other)
    assert (await env.stub_for(env.cook)).status == "issued"


@test
async def test_void_restores_unpaid_until_someone_signs(env):
    e1 = await env.shift(env.cook, utc(MONDAY, 8), 240)
    await env.pay()
    stub = await env.stub_for(env.cook)
    async with env.Session() as db:
        await payr.admin_payroll_void(run_id=stub.pay_run_id, db=db, user=env.admin)
        entry = await db.get(TimeEntry, e1)
        assert entry.status == TimeStatus.CLOSED and entry.pay_run_id is None
        assert (await db.execute(select(PayStub))).scalars().all() == []
    assert len((await env.preview()).workers) == 1


# ==================== screens ====================

@test
async def test_admin_screens_render_in_business_time(env):
    await env.shift(env.cook, utc(SUNDAY, 21), 180)
    await env.shift(env.cook, utc(MONDAY, 8), 240, notes="auto-closed (stale)")
    async with env.Session() as db:
        page = html(await atr.admin_timeclock_view(make_request(method="GET"), db=db, user=env.admin,
                                                   week=None, start=None, end=None, status="all", q_user=None))
        assert f"Pay week {WEEK.label}" in page and "Friday Payroll" in page
        assert "mondayOfWeekET" not in page and "Mark Selected Paid" not in page
        data = json.loads((await atr.admin_timeclock_entries(
            make_request(method="GET"), db=db, user=env.admin, user_id=env.cook.id,
            start=WEEK.start.isoformat(), end=WEEK.end_exclusive.isoformat(), status="all", page=1, page_size=25,
        )).body)
        texts = {e["clock_in_text"] for e in data["entries"]}
        assert any("9:00 PM" in t for t in texts), texts
        assert {e["clock_in_input"] for e in data["entries"]} >= {f"{SUNDAY.isoformat()}T21:00"}

        payroll_page = html(await payr.admin_payroll(make_request(method="GET"), week=None, db=db, user=env.admin))
        assert "Pay week" in payroll_page and "Auto-closed" in payroll_page and "Pay <span id=\"payCount\">1</span>" in payroll_page


@test
async def test_admin_typed_times_are_business_time(env):
    async with env.Session() as db:
        await atr.admin_timeclock_create_entry(
            db=db, user=env.admin, user_id=env.cook.id,
            clock_in=f"{MONDAY.isoformat()}T09:00", clock_out=f"{MONDAY.isoformat()}T13:30", notes="forgot phone",
            start=WEEK.start.isoformat(), end=WEEK.end_exclusive.isoformat())
        entry = (await db.execute(select(TimeEntry))).scalar_one()
    assert entry.clock_in == utc(MONDAY, 9) and entry.duration_minutes == 270
    assert entry.gross_pay == Decimal("90.00")


@test
async def test_clock_in_home_shows_business_time_and_autoclose_pays(env):
    async with env.Session() as db:
        e = await timeclock_service.clock_in(db, TENANT_ID, env.cook.id)
        e.clock_in = utc(MONDAY, 6, 45)
        await db.commit()
        home = html(await wr.worker_home(make_request(method="GET"), db=db, user=env.cook))
    assert "6:45 AM" in home
    async with env.Session() as db:
        await timeclock_service.autoclose_stale_entries(db, TENANT_ID, max_hours=0)
        await db.commit()
        entry = (await db.execute(select(TimeEntry))).scalar_one()
    assert entry.status == TimeStatus.CLOSED and entry.hourly_rate == Decimal("20.00") and entry.gross_pay > 0


@test
async def test_worker_home_shows_only_relevant_actions(env):
    async with env.Session() as db:
        home = html(await wr.worker_home(make_request(method="GET"), db=db, user=env.cook))
        for gone in ("/worker/taskboard", "/worker/orders", "/modules/driver_order", "/worker/menus",
                     "/delivery/driver/", "/worker/shifts"):
            assert gone not in home, gone
        assert home.index("/catering/production") < home.index("/catering/master-calendar") < home.index("/worker/timeclock")
        assert "/shopping/items" in home and "/documents/worker/documents" in home

        driver_home = html(await wr.worker_home(make_request(method="GET"), db=db, user=env.driver))
        assert "/delivery/driver/schedule" in driver_home and "/worker/timeclock" in driver_home
        assert driver_home.count("All your routes") == 0, "the route card above already links to all routes"
        assert "/catering/production" not in driver_home and "/catering/master-calendar" not in driver_home

        from app.api.catering import html_routes as hr
        req = make_request(method="GET")
        cal = html(await hr.master_calendar_view(req, month=None, year=None, db=db, user=env.cook))
        assert "Master Calendar" in cal and "Create Program" not in cal and 'class="cat-nav' not in cal


async def main():
    failed = []
    for fn in TESTS:
        try:
            await with_env(fn)
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed.append(fn.__name__)
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - len(failed)}/{len(TESTS)} passed")
    if failed:
        print("Failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
