"""
Catering Route Board + Packaging + Catering<->Delivery linkage — end-to-end tests.

Runs against a throwaway in-memory SQLite database, calling the real endpoint
functions (with a minimal fake Request) and rendering the real Jinja templates.
No server and no pytest required:

    .venv\\Scripts\\python.exe tests\\test_catering_delivery_flow.py

Safety: DATABASE_URL is forced to in-memory SQLite *before* any app import —
app/db.py loads .env.production, and load_dotenv never overrides a variable
that's already set, so these tests can't reach a real database.
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
from datetime import date, timedelta
from urllib.parse import urlencode

from sqlalchemy import func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import app.models  # noqa: F401 — registers every model on Base.metadata
from app.models.base import Base
from app.models.tenant import Tenant
from app.models.user import User
from app.models.catering import (
    CateringProgram, DailyManifest, DailyManifestStop, DailyManifestItem, ProductionDailyLog,
)
from app.models.delivery import (
    DeliveryStop, DeliveryRoute, DeliveryRouteStop, DeliveryRouteTemplate, DeliveryRouteTemplateStop,
)
from app.schemas.catering import CateringProgramCreate, CateringProgramUpdate
from app.crud.catering import program as program_crud
from app.api.catering import production_routes as pr
from app.api.delivery import driver_routes as dr
from app.api.delivery import template_routes as tr
from app.api.delivery import admin_routes as ar
from app.services.catering import delivery_link as dl

warnings.filterwarnings("ignore")

TENANT_ID = 1
ALL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SERVICE = date.today()          # board edits are only allowed today or later
TOMORROW = SERVICE + timedelta(days=1)


# ==================== harness ====================

def make_request(body=None, form=None, query=None, method="POST"):
    """A Starlette Request carrying a JSON or urlencoded body, as the endpoints expect."""
    if form is not None:
        payload = urlencode(form, doseq=True).encode()
        headers = [(b"content-type", b"application/x-www-form-urlencoded")]
    else:
        payload = json.dumps(body).encode() if body is not None else b""
        headers = [(b"content-type", b"application/json")]
    scope = {
        "type": "http", "method": method, "path": "/", "headers": headers,
        "query_string": urlencode(query or {}).encode(), "session": {}, "state": {},
    }

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    req = Request(scope, receive)
    req.state.tenant_id = TENANT_ID
    return req


def html(resp) -> str:
    return resp.body.decode("utf-8")


def body_json(resp) -> dict:
    return json.loads(resp.body.decode("utf-8"))


class Env:
    """Fresh in-memory database seeded with one tenant, an admin, two drivers and
    five programs on two routes:
        R1: Alpha ("R1-1", legacy), Bravo ("R1-2", legacy), Charlie ("R1", stop 3)
        R2: Delta ("R2", stop 1), Echo ("R2", stop 2)
    """

    async def setup(self):
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)

        async with self.Session() as db:
            db.add(Tenant(id=TENANT_ID, name="Test Kitchen", slug="test-kitchen"))
            self.admin = User(name="Admin", pin_code="1000", role="admin", tenant_id=TENANT_ID, is_active=True)
            self.driver1 = User(name="Driver One", pin_code="2000", role="worker", tenant_id=TENANT_ID, is_active=True)
            self.driver2 = User(name="Driver Two", pin_code="3000", role="worker", tenant_id=TENANT_ID, is_active=True)
            db.add_all([self.admin, self.driver1, self.driver2])
            await db.commit()

        self.p = {}
        for name, code, order in [
            ("Alpha", "R1-1", None), ("Bravo", "R1-2", None), ("Charlie", "R1", 3),
            ("Delta", "R2", 1), ("Echo", "R2", 2),
        ]:
            async with self.Session() as db:
                program = await program_crud.create_program(db, CateringProgramCreate(
                    name=name, client_name=f"{name} Director", client_phone="555-0100",
                    address=f"{len(name)} {name} St", age_group_id=1, total_children=20,
                    breakfast_count=20, invoice_prefix=name[:2].upper(), service_days=ALL_DAYS,
                    meal_types_required=["breakfast"], start_date=SERVICE - timedelta(days=30),
                    route_code=code, breakfast_pack_note=f"2 trays breakfast ({name})",
                    tenant_id=TENANT_ID,
                ))
                if order is not None:
                    program.route_stop_order = order
                    await db.commit()
                self.p[name] = program.id
        return self

    async def close(self):
        await self.engine.dispose()

    # ---------- helpers ----------

    async def manifest(self, route, day=SERVICE):
        async with self.Session() as db:
            return (await db.execute(select(DailyManifest).where(
                DailyManifest.route_code == route, DailyManifest.service_date == day,
            ))).scalar_one_or_none()

    async def route_for(self, route, day=SERVICE):
        m = await self.manifest(route, day)
        if not m:
            return None
        async with self.Session() as db:
            return await dl.delivery_route_for_manifest(db, m.id)

    async def route_stop_names(self, route_id):
        async with self.Session() as db:
            rows = (await db.execute(
                select(DeliveryStop.name)
                .join(DeliveryRouteStop, DeliveryRouteStop.stop_id == DeliveryStop.id)
                .where(DeliveryRouteStop.route_id == route_id)
                .order_by(DeliveryRouteStop.stop_order)
            )).all()
            return [r[0] for r in rows]

    async def manifest_stop_names(self, route, day=SERVICE):
        m = await self.manifest(route, day)
        if not m:
            return []
        async with self.Session() as db:
            rows = (await db.execute(
                select(CateringProgram.name, DailyManifestStop.sort_order)
                .join(DailyManifestStop, DailyManifestStop.program_id == CateringProgram.id)
                .where(DailyManifestStop.manifest_id == m.id)
            )).all()
            return [r[0] for r in sorted(rows, key=lambda r: (r[1], r[0]))]

    async def program(self, name):
        async with self.Session() as db:
            return await db.get(CateringProgram, self.p[name])

    async def build_manifests(self, day=SERVICE):
        """Opening the Manifest Builder creates every serving program's stop."""
        async with self.Session() as db:
            resp = await pr.manifest_builder(make_request(method="GET"), date_str=day.isoformat(), db=db, user=self.admin)
            assert resp.status_code == 200
            return html(resp)

    async def release(self, route, day=SERVICE):
        m = await self.manifest(route, day)
        async with self.Session() as db:
            resp = await pr.manifest_release(make_request(), manifest_id=m.id, db=db, user=self.admin)
            assert resp.status_code == 303

    async def board_save(self, columns, make_permanent=None, day=SERVICE):
        body = {
            "date": day.isoformat(),
            "columns": [{"route": r, "program_ids": [self.p[n] for n in names]} for r, names in columns],
            "make_permanent": [self.p[n] for n in (make_permanent or [])],
        }
        async with self.Session() as db:
            resp = await pr.route_board_save(make_request(body), db=db, user=self.admin)
            assert resp.status_code == 200, html(resp)

    async def link_template(self, route="R1", driver=None, pay="55.00", name=None):
        driver = driver or self.driver1
        dow = SERVICE.weekday()
        form = {
            "name": name or f"{route} Morning", "description": "",
            "catering_route_code": route,
            f"day_{dow}_active": "on", f"day_{dow}_driver_id": driver.id,
            f"pay_rate_{driver.id}": pay,
            "stop_ids[]": [],
        }
        async with self.Session() as db:
            resp = await tr.template_create(make_request(form=form), db=db, user=self.admin)
            assert resp.status_code == 303
        async with self.Session() as db:
            return (await db.execute(select(DeliveryRouteTemplate).where(
                DeliveryRouteTemplate.name == form["name"]))).scalar_one()


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


# ==================== route code parsing ====================

@test
async def test_parse_route_codes(env):
    assert dl.parse_route_code("R1") == ("R1", None)
    assert dl.parse_route_code(" R1-4 ") == ("R1", 4)
    assert dl.parse_route_code("BX-North") == ("BX-North", None)
    assert dl.parse_route_code("") == (None, None)
    assert dl.parse_route_code(None) == (None, None)
    alpha = await env.program("Alpha")
    assert pr._program_route(alpha) == ("R1", 1), "legacy R1-1 reads as route R1, stop 1"
    charlie = await env.program("Charlie")
    assert pr._program_route(charlie) == ("R1", 3)
    charlie.route_code = None
    charlie.route_stop_order = None
    assert pr._program_route(charlie) == (pr.UNASSIGNED_ROUTE, pr.UNORDERED_STOP)
    assert pr._route_color("R1") == pr._route_color("R1", 5), "color is keyed by route number"
    assert pr._sorted_routes(["R10", "Unassigned", "R2", "R1"]) == ["R1", "R2", "R10", "Unassigned"]


# ==================== program <-> delivery stop mirroring ====================

@test
async def test_program_create_update_delete_mirrors_delivery_stop(env):
    async with env.Session() as db:
        stops = (await db.execute(select(DeliveryStop).where(DeliveryStop.catering_program_id.isnot(None)))).scalars().all()
    assert len(stops) == 5, "every created program gets a delivery stop"
    alpha_stop = next(s for s in stops if s.catering_program_id == env.p["Alpha"])
    assert alpha_stop.name == "Alpha" and alpha_stop.contact_name == "Alpha Director" and alpha_stop.is_active

    async with env.Session() as db:
        await program_crud.update_program(db, env.p["Alpha"], TENANT_ID, CateringProgramUpdate(address="99 New Rd", name="Alpha Academy"))
    async with env.Session() as db:
        s = (await db.execute(select(DeliveryStop).where(DeliveryStop.catering_program_id == env.p["Alpha"]))).scalar_one()
    assert s.address == "99 New Rd" and s.name == "Alpha Academy", "program edits flow to the stop"

    async with env.Session() as db:
        await program_crud.update_program(db, env.p["Alpha"], TENANT_ID, CateringProgramUpdate(is_active=False))
    async with env.Session() as db:
        s = await db.get(DeliveryStop, alpha_stop.id)
    assert s.is_active is False, "inactive program -> inactive stop"

    async with env.Session() as db:
        await program_crud.delete_program(db, env.p["Echo"], TENANT_ID)
    async with env.Session() as db:
        echo_stop = (await db.execute(select(DeliveryStop).where(DeliveryStop.name == "Echo"))).scalar_one()
    assert echo_stop.catering_program_id is None and echo_stop.is_active is False, "deleted program's stop is kept, unlinked, inactive"


@test
async def test_backfill_creates_missing_and_fixes_drift(env):
    async with env.Session() as db:
        stop = (await db.execute(select(DeliveryStop).where(DeliveryStop.catering_program_id == env.p["Bravo"]))).scalar_one()
        stop.name = "Drifted"
        await db.delete((await db.execute(select(DeliveryStop).where(DeliveryStop.catering_program_id == env.p["Delta"]))).scalar_one())
        await db.commit()
    async with env.Session() as db:
        created = await dl.ensure_program_delivery_stops(db, TENANT_ID)
    assert created == 1
    async with env.Session() as db:
        names = sorted(s.name for s in (await db.execute(select(DeliveryStop))).scalars().all())
    assert names == ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]


@test
async def test_delivery_stop_admin_locks_program_fields(env):
    async with env.Session() as db:
        resp = await ar.stops_list(make_request(method="GET"), db=db, user=env.admin)
    assert "Catering program" in html(resp)
    async with env.Session() as db:
        stop = (await db.execute(select(DeliveryStop).where(DeliveryStop.catering_program_id == env.p["Alpha"]))).scalar_one()
    async with env.Session() as db:
        await ar.update_stop(make_request(form={"name": "Hacked", "address": "x", "notes": "Gate code 4411"}),
                             stop_id=stop.id, db=db, user=env.admin)
        await ar.delete_stop(make_request(), stop_id=stop.id, db=db, user=env.admin)
    async with env.Session() as db:
        stop = await db.get(DeliveryStop, stop.id)
    assert stop.name == "Alpha" and stop.address == "5 Alpha St", "program-owned fields untouched"
    assert stop.notes == "Gate code 4411", "notes stay editable"
    assert stop.is_active, "can't deactivate a program's stop from delivery"


# ==================== templates ====================

@test
async def test_template_links_catering_route(env):
    async with env.Session() as db:
        resp = await tr.template_create_form(make_request(method="GET", query={"catering_route": "R1"}), db=db, user=env.admin)
    page = html(resp)
    assert 'value="R1" selected' in page, "Set up link preselects the route"

    t1 = await env.link_template("R1")
    assert t1.catering_route_code == "R1"
    async with env.Session() as db:
        t1_loaded = (await dl.catering_route_templates(db, TENANT_ID))["R1"]
        manual_stops = (await db.execute(select(func.count()).select_from(DeliveryRouteTemplateStop).where(
            DeliveryRouteTemplateStop.template_id == t1.id))).scalar()
    assert manual_stops == 0, "catering templates keep no manual stop list"
    assert dl.template_day_for(t1_loaded, SERVICE).driver_id == env.driver1.id

    t2 = await env.link_template("R1", driver=env.driver2, name="R1 Backup")
    async with env.Session() as db:
        t1_after = await db.get(DeliveryRouteTemplate, t1.id)
    assert t2.catering_route_code == "R1" and t1_after.catering_route_code is None, "one template per route"

    async with env.Session() as db:
        resp = await tr.templates_list(make_request(method="GET"), db=db, user=env.admin)
    assert "Catering R1" in html(resp)


@test
async def test_generate_page_excludes_catering_templates(env):
    await env.link_template("R1")
    dow = SERVICE.weekday()
    async with env.Session() as db:
        await tr.template_create(make_request(form={
            "name": "Vending Loop", "description": "", "catering_route_code": "",
            f"day_{dow}_active": "on", f"day_{dow}_driver_id": "", "stop_ids[]": [],
        }), db=db, user=env.admin)
    async with env.Session() as db:
        resp = await tr.generate_form(make_request(method="GET"), week_date=SERVICE.isoformat(), db=db, user=env.admin)
    names = [s["template"].name for s in resp.context["schedule"]]
    assert "Vending Loop" in names and "R1 Morning" not in names, names


# ==================== Route Board ====================

@test
async def test_route_board_renders_columns_in_order(env):
    async with env.Session() as db:
        resp = await pr.route_board(make_request(method="GET"), date_str=SERVICE.isoformat(), db=db, user=env.admin)
    cols = {c["route"]: [s["program"].name for s in c["stops"]] for c in resp.context["columns"]}
    assert cols == {"R1": ["Alpha", "Bravo", "Charlie"], "R2": ["Delta", "Echo"]}, cols
    page = html(resp)
    assert "No driver setup" in page and "catering_route=R1" in page

    await env.link_template("R1")
    async with env.Session() as db:
        resp = await pr.route_board(make_request(method="GET"), date_str=SERVICE.isoformat(), db=db, user=env.admin)
    assert "Driver One" in html(resp), "board shows the template's driver for the day"
    other_day = SERVICE + timedelta(days=1)
    async with env.Session() as db:
        resp = await pr.route_board(make_request(method="GET"), date_str=other_day.isoformat(), db=db, user=env.admin)
    assert "Not scheduled on" in html(resp)


@test
async def test_board_reorder_is_permanent_and_normalizes_legacy_codes(env):
    await env.board_save([("R1", ["Charlie", "Alpha", "Bravo"])])
    alpha, bravo, charlie = [await env.program(n) for n in ("Alpha", "Bravo", "Charlie")]
    assert (charlie.route_stop_order, alpha.route_stop_order, bravo.route_stop_order) == (1, 2, 3)
    assert alpha.route_code == "R1" and bravo.route_code == "R1", "legacy '-N' suffix dropped"
    # A later day with no manifest yet follows the saved order
    async with env.Session() as db:
        resp = await pr.route_board(make_request(method="GET"), date_str=TOMORROW.isoformat(), db=db, user=env.admin)
    cols = {c["route"]: [s["program"].name for s in c["stops"]] for c in resp.context["columns"]}
    assert cols["R1"] == ["Charlie", "Alpha", "Bravo"], cols


@test
async def test_board_rejects_past_dates(env):
    async with env.Session() as db:
        resp = await pr.route_board_save(make_request({"date": (SERVICE - timedelta(days=1)).isoformat(), "columns": []}),
                                         db=db, user=env.admin)
    assert resp.status_code == 400


@test
async def test_day_only_move_then_make_permanent(env):
    await env.build_manifests()
    await env.board_save([("R1", ["Alpha", "Delta", "Bravo", "Charlie"]), ("R2", ["Echo"])])
    assert await env.manifest_stop_names("R1") == ["Alpha", "Delta", "Bravo", "Charlie"]
    assert await env.manifest_stop_names("R2") == ["Echo"]
    delta = await env.program("Delta")
    assert delta.route_code == "R2" and delta.route_stop_order == 1, "day-only move leaves the permanent route alone"

    # Packaging screen groups by today's route and flags the move
    async with env.Session() as db:
        data = await pr._build_production_data(db, TENANT_ID, SERVICE)
    groups = {g["route_code"]: [pd["program"].name for pd in g["programs"]] for g in data["route_groups"]}
    assert groups["R1"] == ["Alpha", "Delta", "Bravo", "Charlie"], groups
    delta_pd = next(pd for pd in data["programs_data"] if pd["program"].name == "Delta")
    assert delta_pd["is_moved_today"] and delta_pd["home_route"] == "R2"

    # Tomorrow Delta is back on R2
    async with env.Session() as db:
        resp = await pr.route_board(make_request(method="GET"), date_str=TOMORROW.isoformat(), db=db, user=env.admin)
    cols = {c["route"]: [s["program"].name for s in c["stops"]] for c in resp.context["columns"]}
    assert "Delta" in cols["R2"] and "Delta" not in cols["R1"], cols

    await env.board_save([("R1", ["Alpha", "Delta", "Bravo", "Charlie"])], make_permanent=["Delta"])
    delta = await env.program("Delta")
    assert delta.route_code == "R1" and delta.route_stop_order == 2


@test
async def test_route_code_chip_moves_upcoming_stops(env):
    await env.build_manifests()
    await env.build_manifests(TOMORROW)
    async with env.Session() as db:
        resp = await pr.save_route_code(make_request({"program_id": env.p["Charlie"], "route_code": "R2"}), db=db, user=env.admin)
    assert body_json(resp)["moved_stops"] == 2, "today's and tomorrow's stops moved"
    assert "Charlie" in await env.manifest_stop_names("R2") and "Charlie" in await env.manifest_stop_names("R2", TOMORROW)
    charlie = await env.program("Charlie")
    assert charlie.route_code == "R2" and charlie.route_stop_order is None, "new route: goes to the end"

    async with env.Session() as db:
        await pr.save_route_code(make_request({"program_id": env.p["Charlie"], "route_code": "R3-7"}), db=db, user=env.admin)
    charlie = await env.program("Charlie")
    assert (charlie.route_code, charlie.route_stop_order) == ("R3", 7), "typing R3-7 still works"

    async with env.Session() as db:
        await pr.save_route_code(make_request({"program_id": env.p["Alpha"], "route_code": "R1"}), db=db, user=env.admin)
    alpha = await env.program("Alpha")
    assert (alpha.route_code, alpha.route_stop_order) == ("R1", 1), "same route keeps its legacy position"


# ==================== Packaging: beverage ====================

@test
async def test_beverage_multi_select_manifest_lines(env):
    async with env.Session() as db:
        resp = await pr.save_supply_selection(make_request({
            "date": SERVICE.isoformat(), "program_id": env.p["Alpha"], "supply": "beverage", "items": ["Water", "Milk", "Soda"],
        }), db=db, user=env.admin)
    assert body_json(resp)["items"] == ["Milk", "Water"], "known beverages only, in option order"

    async def lines(program):
        async with env.Session() as db:
            rows = (await db.execute(
                select(DailyManifestItem.source, DailyManifestItem.label)
                .join(DailyManifestStop, DailyManifestItem.stop_id == DailyManifestStop.id)
                .where(DailyManifestStop.program_id == env.p[program])
                .order_by(DailyManifestItem.sort_order)
            )).all()
            return [tuple(r) for r in rows]

    assert await lines("Alpha") == [("beverage", "Milk"), ("beverage", "Water")]

    # A legacy Milk checkbox from before the change is replaced, not duplicated
    stop, _ = None, None
    async with env.Session() as db:
        bravo = await db.get(CateringProgram, env.p["Bravo"])
        stop = await pr._get_or_create_stop(db, TENANT_ID, bravo, SERVICE)
        db.add(DailyManifestItem(id="legacy-milk", stop_id=stop.id, source="milk", label="Milk", sort_order=5))
        db.add(ProductionDailyLog(id="legacy-log", tenant_id=TENANT_ID, service_date=SERVICE, program_id=env.p["Bravo"],
                                  check_type="milk", checked_by_user_id=env.admin.id))
        await db.commit()
    async with env.Session() as db:
        data = await pr._build_production_data(db, TENANT_ID, SERVICE)
    bravo_pd = next(pd for pd in data["programs_data"] if pd["program"].name == "Bravo")
    assert bravo_pd["supply_checks"]["beverage"]["selected_items"] == ["Milk"], "legacy milk reads as Beverage"

    async with env.Session() as db:
        await pr.save_supply_selection(make_request({
            "date": SERVICE.isoformat(), "program_id": env.p["Bravo"], "supply": "beverage", "items": ["Juice"],
        }), db=db, user=env.admin)
    assert await lines("Bravo") == [("beverage", "Juice")]
    async with env.Session() as db:
        legacy_logs = (await db.execute(select(func.count()).select_from(ProductionDailyLog).where(
            ProductionDailyLog.check_type == "milk"))).scalar()
    assert legacy_logs == 0

    async with env.Session() as db:
        resp = await pr.save_supply_selection(make_request({
            "date": SERVICE.isoformat(), "program_id": env.p["Bravo"], "supply": "beverage", "items": [],
        }), db=db, user=env.admin)
    assert body_json(resp)["checked"] is False and await lines("Bravo") == []

    async with env.Session() as db:
        resp = await pr.save_supply_selection(make_request({
            "date": SERVICE.isoformat(), "program_id": env.p["Bravo"], "supply": "milk", "items": ["Milk"],
        }), db=db, user=env.admin)
    assert resp.status_code == 400, "old supply types are rejected"


@test
async def test_packaging_page_renders(env):
    await env.board_save([("R1", ["Alpha", "Delta", "Bravo", "Charlie"])])
    async with env.Session() as db:
        resp = await pr.production_daily_view(make_request(method="GET"), date_str=SERVICE.isoformat(), selected=None,
                                              db=db, user=env.admin)
    page = html(resp)
    for expected in ("Beverage", "Route Board", "R1 · Stop 1", "today only · usually R2", 'data-beverage="Water"'):
        assert expected in page, expected


# ==================== phase 2: manifest release -> delivery route ====================

@test
async def test_release_creates_driver_route_with_template_driver_and_pay(env):
    await env.link_template("R1", pay="55.00")
    await env.build_manifests()
    assert await env.route_for("R1") is None, "no driver route before release"
    await env.release("R1")

    route = await env.route_for("R1")
    assert route is not None
    assert route.assigned_driver_id == env.driver1.id and route.status == "assigned"
    assert float(route.driver_pay_rate) == 55.0 and route.name == "R1 Morning" and route.date == SERVICE
    assert await env.route_stop_names(route.id) == ["Alpha", "Bravo", "Charlie"]

    await env.release("R2")  # no template -> open route any driver can pick up
    r2 = await env.route_for("R2")
    assert r2.assigned_driver_id is None and r2.status == "draft" and r2.name == "R2"
    assert await env.route_stop_names(r2.id) == ["Delta", "Echo"]

    await env.release("R1")  # re-release doesn't duplicate
    async with env.Session() as db:
        count = (await db.execute(select(func.count()).select_from(DeliveryRoute))).scalar()
    assert count == 2

    async with env.Session() as db:
        resp = await dr.driver_routes_list(make_request(method="GET"), db=db, user=env.driver1)
    page = html(resp)
    assert "R1 Morning" in page, "driver one sees their route"
    assert "R2" in page, "open R2 is listed as available"


@test
async def test_board_changes_resync_driver_routes(env):
    await env.link_template("R1")
    await env.build_manifests()
    await env.release("R1")
    await env.release("R2")
    r1, r2 = await env.route_for("R1"), await env.route_for("R2")

    await env.board_save([("R1", ["Charlie", "Alpha", "Bravo"])])
    assert await env.route_stop_names(r1.id) == ["Charlie", "Alpha", "Bravo"], "reorder flows to the driver"

    await env.board_save([("R1", ["Charlie", "Delta", "Alpha", "Bravo"]), ("R2", ["Echo"])])
    assert await env.route_stop_names(r1.id) == ["Charlie", "Delta", "Alpha", "Bravo"]
    assert await env.route_stop_names(r2.id) == ["Echo"], "moved stop leaves the other driver's route"


@test
async def test_driver_progress_is_never_undone(env):
    await env.link_template("R1")
    await env.build_manifests()
    await env.release("R1")
    await env.release("R2")
    r1 = await env.route_for("R1")

    # Driver already delivered Bravo; a "pick up trays" stop was added by hand first
    async with env.Session() as db:
        bravo_rs = (await db.execute(
            select(DeliveryRouteStop).join(DeliveryStop, DeliveryRouteStop.stop_id == DeliveryStop.id)
            .where(DeliveryRouteStop.route_id == r1.id, DeliveryStop.name == "Bravo"))).scalar_one()
        bravo_rs.status = "completed"
        trays = DeliveryStop(id="trays", name="Pick up trays", tenant_id=TENANT_ID, is_active=True)
        db.add(trays)
        db.add(DeliveryRouteStop(id="trays-rs", route_id=r1.id, stop_id="trays", stop_order=0, status="pending"))
        await db.commit()

    # Route was: trays, Alpha, Bravo(delivered), Charlie. Move Bravo to R2 and swap the rest.
    await env.board_save([("R1", ["Charlie", "Alpha"]), ("R2", ["Delta", "Echo", "Bravo"])])
    names = await env.route_stop_names(r1.id)
    # Fixed stops (the manual extra, the delivered Bravo) hold their slots; program
    # stops fill the remaining slots in the new board order.
    assert names == ["Pick up trays", "Charlie", "Bravo", "Alpha"], names

    # A completed route is history: board changes don't touch it
    async with env.Session() as db:
        (await db.get(DeliveryRoute, r1.id)).status = "completed"
        await db.commit()
    await env.board_save([("R1", ["Alpha", "Charlie"])])
    assert await env.route_stop_names(r1.id) == ["Pick up trays", "Charlie", "Bravo", "Alpha"]


@test
async def test_new_stop_on_released_manifest_reaches_driver(env):
    await env.link_template("R1")
    # Only Alpha has anything checked, so only Alpha's stop exists at release
    async with env.Session() as db:
        await pr.save_supply_selection(make_request({
            "date": SERVICE.isoformat(), "program_id": env.p["Alpha"], "supply": "beverage", "items": ["Milk"],
        }), db=db, user=env.admin)
    await env.release("R1")
    r1 = await env.route_for("R1")
    assert await env.route_stop_names(r1.id) == ["Alpha"]

    # Kitchen packs Bravo after release -> Bravo's new stop joins the driver's route
    async with env.Session() as db:
        await pr.save_supply_selection(make_request({
            "date": SERVICE.isoformat(), "program_id": env.p["Bravo"], "supply": "beverage", "items": ["Juice"],
        }), db=db, user=env.admin)
    assert await env.route_stop_names(r1.id) == ["Alpha", "Bravo"]


@test
async def test_emptied_reopened_manifest_retires_unstarted_route(env):
    await env.build_manifests()
    await env.release("R2")
    r2 = await env.route_for("R2")
    r2_manifest = await env.manifest("R2")
    async with env.Session() as db:
        await pr.manifest_reopen(make_request(), manifest_id=r2_manifest.id, db=db, user=env.admin)

    await env.board_save([("R1", ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]), ("R2", [])])
    assert await env.manifest("R2") is None, "empty draft manifest removed"
    async with env.Session() as db:
        assert await db.get(DeliveryRoute, r2.id) is None, "never-started driver route removed with it"


@test
async def test_driver_route_view_shows_manifest_checklist(env):
    await env.link_template("R1")
    async with env.Session() as db:
        await pr.save_supply_selection(make_request({
            "date": SERVICE.isoformat(), "program_id": env.p["Alpha"], "supply": "beverage", "items": ["Milk", "Water"],
        }), db=db, user=env.admin)
        await pr.save_supply_selection(make_request({
            "date": SERVICE.isoformat(), "program_id": env.p["Alpha"], "supply": "produce", "items": ["Apples"],
        }), db=db, user=env.admin)
    await env.build_manifests()
    await env.release("R1")
    r1 = await env.route_for("R1")

    async with env.Session() as db:
        resp = await dr.driver_route_view(make_request(method="GET"), route_id=r1.id, db=db, user=env.driver1)
    page = html(resp)
    for label in ("Milk", "Water", "Apples", "stop-item"):
        assert label in page, label
    assert "/catering/production/manifest/driver/view?date_str" not in page, "separate manifest link hidden for catering routes"

    async with env.Session() as db:
        item = (await db.execute(select(DailyManifestItem).where(DailyManifestItem.label == "Milk"))).scalar_one()
    async with env.Session() as db:
        resp = await dr.toggle_manifest_item(make_request(), item_id=item.id, db=db, user=env.driver1)
    assert body_json(resp) == {"confirmed": True}
    async with env.Session() as db:
        resp = await dr.toggle_manifest_item(make_request(), item_id=item.id, db=db, user=env.driver2)
    assert resp.status_code == 403, "another driver can't check off this route's items"
    async with env.Session() as db:
        item = await db.get(DailyManifestItem, item.id)
    assert item.driver_confirmed and item.driver_confirmed_by_user_id == env.driver1.id


@test
async def test_catering_manifest_page_sends_drivers_to_delivery_app(env):
    await env.link_template("R1")
    await env.build_manifests()
    await env.release("R1")
    r1 = await env.route_for("R1")
    async with env.Session() as db:
        resp = await pr.driver_manifest_detail(make_request(method="GET"), route_code="R1",
                                               date_str=SERVICE.isoformat(), db=db, user=env.driver1)
    assert resp.status_code == 303 and resp.headers["location"] == f"/delivery/driver/route/{r1.id}"
    async with env.Session() as db:
        resp = await pr.driver_manifest_detail(make_request(method="GET"), route_code="R1",
                                               date_str=SERVICE.isoformat(), db=db, user=env.admin)
    assert resp.status_code == 200 and "Stop 1" in html(resp), "admins keep the printable manifest"


@test
async def test_manifest_builder_lists_stops_in_board_order(env):
    await env.board_save([("R1", ["Charlie", "Bravo", "Alpha"])])
    page = await env.build_manifests()
    assert page.index("Charlie") < page.index("Bravo") < page.index("Alpha")
    assert "Route Board" in page


# ==================== runner ====================

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
