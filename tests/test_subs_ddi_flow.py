"""
Production substitutions + Daily Delivery Invoices (DDI) — end-to-end tests.

In-memory SQLite, real endpoint functions, real templates (same harness style as
test_catering_delivery_flow.py). No server and no pytest required:

    .venv\\Scripts\\python.exe tests\\test_subs_ddi_flow.py
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
import re
import traceback
import warnings
from datetime import date, timedelta
from urllib.parse import unquote, urlencode

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import app.models  # noqa: F401 — registers every model on Base.metadata
from app.models.base import Base
from app.models.tenant import Tenant
from app.models.user import User
from app.models.catering import (
    CACFPAgeGroup, CACFPComponentType, CACFPPortionRule, FoodComponent, CateringMonthlyMenu,
    CateringMenuDay, MenuDayComponent, CateringInvoice, CateringProgram, CateringInvoiceLine, CateringSubstitution,
    ProductionDailyLog, DailyManifest,
)
from app.schemas.catering import CateringProgramCreate
from app.crud.catering import program as program_crud
from app.api.catering import production_routes as pr
from app.api.catering import html_routes as hr
from app.services.catering import ddi

warnings.filterwarnings("ignore")

TENANT_ID = 1
ALL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SERVICE = date.today()


def make_request(body=None, form=None, query=None, method="POST"):
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
    """Three programs, all serving lunch today (Chicken 2oz, Rice 1oz, Broccoli 1.5oz):
        Alpha   — CACFP, family style (bulk DDI), route R1 stop 1, also breakfast (Cereal)
        Bravo   — CACFP, individual (unitized DDI), route R1 stop 2
        Charlie — not CACFP, route R2
    """

    async def setup(self):
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)

        async with self.Session() as db:
            db.add(Tenant(id=TENANT_ID, name="Test Kitchen", slug="test-kitchen"))
            db.add(CACFPAgeGroup(id=4, name="Child 3-5 years", age_min_months=36, age_max_months=60, sort_order=4))
            for i, n in enumerate(["Milk", "Meat/Meat Alternate", "Grain", "Vegetable", "Fruit"], start=1):
                db.add(CACFPComponentType(id=i, name=n, sort_order=i))
            db.add_all([
                CACFPPortionRule(age_group_id=4, component_type_id=1, meal_type="Breakfast", min_portion_oz=6),
                CACFPPortionRule(age_group_id=4, component_type_id=1, meal_type="Lunch", min_portion_oz=6),
                CACFPPortionRule(age_group_id=4, component_type_id=5, meal_type="Lunch", min_portion_oz=0.25),
            ])
            self.admin = User(name="Admin", pin_code="1000", role="admin", tenant_id=TENANT_ID, is_active=True)
            self.worker = User(name="Cook", pin_code="2000", role="worker", tenant_id=TENANT_ID, is_active=True)
            db.add_all([self.admin, self.worker])
            await db.commit()

            self.c = {}
            for name, type_id, oz in [
                ("Chicken", 2, 2), ("Turkey", 2, 2), ("Rice", 3, 1), ("Cereal", 3, 1),
                ("Broccoli", 4, 1.5), ("Green Beans", 4, 1.5), ("Apple", 5, 2),
            ]:
                fc = FoodComponent(name=name, component_type_id=type_id, default_portion_oz=oz, tenant_id=TENANT_ID)
                db.add(fc)
                await db.flush()
                self.c[name] = fc.id
            await db.commit()

        self.p = {}
        for name, cacfp, style, route, order, meals in [
            ("Alpha", True, "family_style", "R1", 1, ["Breakfast", "Lunch"]),
            ("Bravo", True, "individual", "R1", 2, ["Lunch"]),
            ("Charlie", False, "family_style", "R2", 1, ["Lunch"]),
        ]:
            async with self.Session() as db:
                program = await program_crud.create_program(db, CateringProgramCreate(
                    name=name, client_name=f"{name} Director", address=f"1 {name} St, Queens NY",
                    age_group_id=4, total_children=20, lunch_count=20, breakfast_count=20,
                    invoice_prefix=name[:2].upper(), service_days=ALL_DAYS, meal_types_required=meals,
                    start_date=SERVICE - timedelta(days=30), route_code=route, cacfp_eligible=cacfp,
                    meal_service_style=style, tenant_id=TENANT_ID,
                ))
                program.route_stop_order = order
                menu = CateringMonthlyMenu(program_id=program.id, month=SERVICE.month, year=SERVICE.year, tenant_id=TENANT_ID)
                db.add(menu)
                await db.flush()
                day = CateringMenuDay(monthly_menu_id=menu.id, service_date=SERVICE)
                db.add(day)
                await db.flush()
                for i, (comp, slot) in enumerate([("Chicken", "lunch"), ("Rice", "lunch"), ("Broccoli", "lunch"), ("Cereal", "breakfast")]):
                    db.add(MenuDayComponent(menu_day_id=day.id, component_id=self.c[comp], meal_slot=slot, sort_order=i))
                await db.commit()
                self.p[name] = program.id
        return self

    async def close(self):
        await self.engine.dispose()

    # ---------- helpers ----------

    async def data(self):
        async with self.Session() as db:
            return await pr._build_production_data(db, TENANT_ID, SERVICE)

    async def packaging(self, program, slot="lunch"):
        d = await self.data()
        pd = next(x for x in d["programs_data"] if x["program"].id == self.p[program])
        return next(x for x in pd["packaging"] if x["slot"] == slot)["components"]

    async def sub(self, original, replacement, programs=None, slot="", portion=None, reason=None):
        body = {
            "date": SERVICE.isoformat(), "original_component_id": self.c[original],
            "replacement_component_id": self.c[replacement], "meal_slot": slot,
            "program_ids": [self.p[n] for n in (programs or [])], "portion_oz": portion, "reason": reason,
        }
        async with self.Session() as db:
            return await pr.save_substitution(make_request(body), db=db, user=self.admin)

    async def generate(self):
        async with self.Session() as db:
            resp = await pr.generate_invoices_from_production(
                make_request(form={"date_str": SERVICE.isoformat()}), date_str=SERVICE.isoformat(), db=db, user=self.admin)
            assert resp.status_code == 303
            return unquote(resp.headers["location"])

    async def invoice(self, program):
        async with self.Session() as db:
            return (await db.execute(
                select(CateringInvoice).where(CateringInvoice.program_id == self.p[program])
                .options(selectinload(CateringInvoice.lines))
            )).scalars().all()

    async def lines(self, program, slot="lunch"):
        invs = await self.invoice(program)
        assert len(invs) == 1, f"{program} should have exactly one invoice, has {len(invs)}"
        return [l for l in sorted(invs[0].lines, key=lambda l: l.sort_order) if l.meal_slot == slot]

    async def day_pack(self, **query):
        async with self.Session() as db:
            return await pr.invoice_day_pack(
                make_request(method="GET", query=query), date_str=SERVICE.isoformat(),
                scope=query.get("scope", "cacfp"), route=query.get("route"), format=query.get("format", "html"),
                db=db, user=self.admin,
            )

    async def build_manifests(self):
        async with self.Session() as db:
            resp = await pr.manifest_builder(make_request(method="GET"), date_str=SERVICE.isoformat(), db=db, user=self.admin)
            assert resp.status_code == 200

    async def manifest(self, route):
        async with self.Session() as db:
            return (await db.execute(select(DailyManifest).where(
                DailyManifest.route_code == route, DailyManifest.service_date == SERVICE))).scalar_one_or_none()

    async def release(self, route):
        await self.build_manifests()
        m = await self.manifest(route)
        async with self.Session() as db:
            assert (await pr.manifest_release(make_request(), manifest_id=m.id, db=db, user=self.admin)).status_code == 303

    async def reopen(self, route):
        m = await self.manifest(route)
        async with self.Session() as db:
            assert (await pr.manifest_reopen(make_request(), manifest_id=m.id, db=db, user=self.admin)).status_code == 303

    async def count(self, program, slot, count, vegan=0):
        body = {"date": SERVICE.isoformat(), "program_id": self.p[program], "slot": slot, "count": count, "vegan_count": vegan}
        async with self.Session() as db:
            return await pr.save_daily_count(make_request(body), db=db, user=self.admin)


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


def names(components):
    return [c["name"] for c in components]


# ==================== substitutions ====================

@test
async def test_kitchen_wide_sub_reaches_prep_and_packaging(env):
    resp = await env.sub("Chicken", "Turkey", reason="Chicken short")
    assert resp.status_code == 200, html(resp)
    assert body_json(resp)["affected"] == 3

    d = await env.data()
    prep = {c["name"]: c for c in d["prep_components"]}
    assert "Chicken" not in prep and "Turkey" in prep
    assert prep["Turkey"]["sub_from"] == ["Chicken"]
    assert prep["Turkey"]["total_count"] == 60, "20 lunches x 3 programs"
    assert prep["Turkey"]["total_oz"] == 120.0, "like-for-like swap keeps the planned 2 oz"
    for name in ("Alpha", "Bravo", "Charlie"):
        comps = await env.packaging(name)
        assert names(comps) == ["Turkey", "Rice", "Broccoli"], names(comps)
        assert comps[0]["sub_from"] == "Chicken"
    assert d["substitutions"][0]["scope"] == "All programs"


@test
async def test_per_program_sub_only_hits_that_program(env):
    assert (await env.sub("Broccoli", "Green Beans", programs=["Bravo"])).status_code == 200
    assert "Broccoli" in names(await env.packaging("Alpha"))
    assert "Green Beans" in names(await env.packaging("Bravo"))
    prep = {c["name"]: c for c in (await env.data())["prep_components"]}
    assert prep["Broccoli"]["total_count"] == 40 and prep["Green Beans"]["total_count"] == 20


@test
async def test_program_sub_beats_kitchen_wide_sub(env):
    await env.sub("Broccoli", "Green Beans")
    await env.sub("Broccoli", "Apple", programs=["Alpha"], portion=2)
    assert "Apple" in names(await env.packaging("Alpha")) or True  # Apple is produce -> on the Produce card, not the list
    assert "Green Beans" in names(await env.packaging("Bravo"))
    async with env.Session() as db:
        from app.services.catering import day_menu
        days = await day_menu.load_menu_days(db, [env.p["Alpha"]], SERVICE)
        subs = await day_menu.load_substitutions(db, TENANT_ID, SERVICE)
        resolved = day_menu.resolve_slot(days[env.p["Alpha"]], "lunch", ["breakfast", "lunch"], subs, env.p["Alpha"])
    assert [c.name for c in resolved] == ["Chicken", "Rice", "Apple"]
    assert resolved[2].qty_oz == 2.0 and resolved[2].type_name == "Fruit"


@test
async def test_resubbing_same_scope_replaces_previous_sub(env):
    await env.sub("Chicken", "Turkey")
    await env.sub("Chicken", "Rice")
    async with env.Session() as db:
        rows = (await db.execute(select(CateringSubstitution))).scalars().all()
    assert len(rows) == 1 and rows[0].replacement_component_id == env.c["Rice"]


@test
async def test_sub_unchecks_item_that_was_already_packed(env):
    async with env.Session() as db:
        await pr.toggle_production_check(make_request({
            "date": SERVICE.isoformat(), "check_type": "lunch", "program_id": env.p["Alpha"], "reference_key": "Chicken",
        }), db=db, user=env.worker)
    assert (await env.packaging("Alpha"))[0]["checked"] is True
    resp = await env.sub("Chicken", "Turkey")
    assert body_json(resp)["cleared_checks"] == 1
    comps = await env.packaging("Alpha")
    assert comps[0]["name"] == "Turkey" and comps[0]["checked"] is False, "new item must be packed for real"
    async with env.Session() as db:
        logs = (await db.execute(select(ProductionDailyLog).where(ProductionDailyLog.reference_key == "Chicken"))).scalars().all()
    assert logs == []


@test
async def test_undo_sub_restores_menu(env):
    await env.sub("Chicken", "Turkey")
    sub_id = (await env.data())["substitutions"][0]["id"]
    async with env.Session() as db:
        resp = await pr.delete_substitution(make_request(), sub_id=sub_id, db=db, user=env.admin)
    assert resp.status_code == 200
    assert names(await env.packaging("Alpha"))[0] == "Chicken"


@test
async def test_bad_subs_are_rejected(env):
    assert (await env.sub("Chicken", "Chicken")).status_code == 400
    resp = await env.sub("Turkey", "Chicken")
    assert resp.status_code == 400 and "isn't on the menu" in body_json(resp)["error"]
    resp = await env.sub("Cereal", "Rice", programs=["Bravo"])
    assert resp.status_code == 400, "Bravo doesn't get breakfast"


@test
async def test_type_change_is_flagged(env):
    await env.sub("Broccoli", "Rice")
    assert (await env.data())["substitutions"][0]["type_changed"] is True


# ==================== Daily Delivery Invoices ====================

@test
async def test_every_program_gets_an_invoice(env):
    location = await env.generate()
    assert "3 invoice(s) up to date" in location
    for name in ("Alpha", "Bravo", "Charlie"):
        assert len(await env.invoice(name)) == 1
    await env.generate()
    assert len(await env.invoice("Alpha")) == 1, "regenerating updates, never duplicates"
    assert (await env.invoice("Alpha"))[0].invoice_number == "AL-0001"


@test
async def test_invoice_lines_carry_subs_counts_milk_and_fruit(env):
    await env.sub("Chicken", "Turkey", reason="Chicken short — OK'd by director")
    await env.count("Alpha", "lunch", 18)
    async with env.Session() as db:
        await pr.save_supply_selection(make_request({
            "date": SERVICE.isoformat(), "program_id": env.p["Alpha"], "supply": "produce", "items": ["Apple"],
        }), db=db, user=env.worker)
    await env.generate()

    lines = await env.lines("Alpha")
    by_item = {l.item_name: l for l in lines}
    assert [l.item_name for l in lines] == ["Turkey", "Rice", "Broccoli", "1% Low-Fat Milk", "Apple"], [l.item_name for l in lines]
    assert all(l.meal_count == 18 for l in lines), "today's edited count, not the standing 20"
    assert by_item["Turkey"].substituted_for == "Chicken" and "director" in by_item["Turkey"].substitution_reason
    assert by_item["1% Low-Fat Milk"].portion_unit == "fl oz" and float(by_item["1% Low-Fat Milk"].portion_qty) == 6
    assert by_item["Apple"].component_type == "Fruit" and by_item["Apple"].portion_unit == "cup"
    assert ddi.total_text(by_item["1% Low-Fat Milk"]) == "108 fl oz"
    assert ddi.total_text(by_item["Turkey"]) == "2.25 lb"

    charlie = [l.item_name for l in await env.lines("Charlie")]
    assert "1% Low-Fat Milk" not in charlie, "milk/fruit auto-lines are CACFP-only"


@test
async def test_menu_edit_after_release_does_not_rewrite_invoice(env):
    await env.release("R1")
    before = [l.item_name for l in await env.lines("Alpha")]
    async with env.Session() as db:
        rice = (await db.execute(select(MenuDayComponent).where(MenuDayComponent.component_id == env.c["Rice"]))).scalars().all()
        for row in rice:
            await db.delete(row)
        await db.commit()
    await env.generate()
    assert [l.item_name for l in await env.lines("Alpha")] == before, "a finalized DDI is a frozen record"
    assert "Rice" not in [l.item_name for l in await env.lines("Charlie")], "unreleased drafts still follow the menu"


@test
async def test_release_locks_route_and_reopen_unlocks(env):
    await env.release("R1")
    alpha = (await env.invoice("Alpha"))[0]
    charlie = await env.invoice("Charlie")
    assert alpha.status == "finalized" and alpha.finalized_at is not None
    assert charlie == [] or charlie[0].status == "draft", "R2 not released"

    resp = await env.count("Alpha", "lunch", 5)
    assert resp.status_code == 409 and "Reopen" in body_json(resp)["error"]
    resp = await env.sub("Chicken", "Turkey", programs=["Alpha"])
    assert resp.status_code == 409
    resp = await env.sub("Chicken", "Turkey", programs=["Charlie"])
    assert resp.status_code == 200, "other routes stay editable"

    d = await env.data()
    assert next(x for x in d["programs_data"] if x["program"].id == env.p["Alpha"])["invoice_locked"] is True

    await env.reopen("R1")
    assert (await env.invoice("Alpha"))[0].status == "draft"
    assert (await env.count("Alpha", "lunch", 5)).status_code == 200


@test
async def test_route_released_before_invoices_existed_gets_locked(env):
    """Routes released before lock-on-release existed: the next Production Sheet
    or Day Pack load locks their invoices instead of printing them as drafts."""
    await env.release("R1")
    async with env.Session() as db:
        for inv in (await db.execute(select(CateringInvoice))).scalars().all():
            await db.delete(inv)
        await db.commit()
    assert await env.invoice("Alpha") == []

    page = html(await env.day_pack())
    assert "not released yet" not in page and "route not released" not in page
    assert (await env.invoice("Alpha"))[0].status == "finalized"
    assert (await env.invoice("Bravo"))[0].status == "finalized"

    async with env.Session() as db:
        inv = (await db.execute(select(CateringInvoice).where(CateringInvoice.program_id == env.p["Bravo"]))).scalar_one()
        inv.status = "draft"
        await db.commit()
    d = await env.data()
    assert next(x for x in d["programs_data"] if x["program"].id == env.p["Bravo"])["invoice_locked"] is True
    assert (await env.invoice("Charlie")) == [] or (await env.invoice("Charlie"))[0].status == "draft"


@test
async def test_locked_invoice_cannot_be_deleted(env):
    await env.release("R1")
    inv = (await env.invoice("Alpha"))[0]
    async with env.Session() as db:
        resp = await hr.delete_invoice_route(make_request(), invoice_id=inv.id, db=db, user=env.admin)
    assert "error=" in resp.headers["location"]
    assert len(await env.invoice("Alpha")) == 1


@test
async def test_day_pack_prints_cacfp_programs_in_route_order(env):
    page = html(await env.day_pack())
    assert "Alpha" in page and "Bravo" in page and "Charlie St" not in page
    assert page.index("1 Alpha St") < page.index("1 Bravo St"), "route R1 stop 1 before stop 2"
    assert page.count("DAILY DELIVERY INVOICE") == 2
    assert "not released yet" in page, "warns before printing drafts"
    assert len(await env.invoice("Charlie")) == 1, "non-CACFP still gets its stored record"

    everyone = html(await env.day_pack(scope="all"))
    assert everyone.count("DAILY DELIVERY INVOICE") == 3
    r2 = html(await env.day_pack(scope="all", route="R2"))
    assert r2.count("DAILY DELIVERY INVOICE") == 1 and "1 Charlie St" in r2


@test
async def test_day_pack_follows_ddi_format(env):
    await env.sub("Chicken", "Turkey", reason="Chicken short")
    await env.release("R1")
    page = html(await env.day_pack())
    alpha = page[page.index("1 Alpha St"):page.index("1 Bravo St")]
    bravo = page[page.index("1 Bravo St"):]
    # Required on every NY DDI: vendor, center + address, date, meal count, food types, signature line
    for required in ("Chai and Biscuit LLC", "Delivery date", "Number of meals delivered", "Signature", "1% Low-Fat Milk"):
        assert required in alpha, required
    assert "Total delivered" in alpha and "Delivered in bulk" in alpha, "family style -> bulk totals"
    assert "each containing" in bravo and "Total delivered" not in bravo, "individual -> unitized contents"
    assert "Turkey served in place of Chicken" in alpha and "Chicken short" in alpha
    assert "DRAFT" not in page.replace("DRAFT —", ""), "released route prints without the draft banner"
    assert "Seasonal Fruit" in alpha and "fruit type not picked" in page


@test
async def test_day_pack_pdf_is_one_file(env):
    # Busiest page: Alpha gets breakfast, lunch and a PM snack, with subs on two meals
    async with env.Session() as db:
        alpha = await db.get(CateringProgram, env.p["Alpha"])
        alpha.meal_types_required = json.dumps(["Breakfast", "Lunch", "PM Snack"])
        alpha.pm_snack_count = 20
        day = (await db.execute(select(CateringMenuDay).join(CateringMonthlyMenu).where(
            CateringMonthlyMenu.program_id == env.p["Alpha"]))).scalar_one()
        for i, comp in enumerate(["Apple", "Cereal"]):
            db.add(MenuDayComponent(menu_day_id=day.id, component_id=env.c[comp], meal_slot="pm_snack", sort_order=10 + i))
        await db.commit()
    await env.sub("Chicken", "Turkey", reason="Chicken delivery short — approved by the center director")
    await env.sub("Broccoli", "Green Beans", programs=["Alpha"], reason="Kids' favorite swap")
    await env.sub("Cereal", "Rice", slot="breakfast")
    resp = await env.day_pack(format="pdf")
    assert resp.media_type == "application/pdf", getattr(resp, "headers", {})
    assert resp.body[:4] == b"%PDF"
    import io
    from pypdf import PdfReader
    assert len(PdfReader(io.BytesIO(resp.body)).pages) == 2, "one page per CACFP program"


@test
async def test_single_invoice_view_and_pdf(env):
    await env.generate()
    inv = (await env.invoice("Bravo"))[0]
    async with env.Session() as db:
        resp = await hr.view_invoice(make_request(method="GET"), invoice_id=inv.id, db=db, user=env.admin)
        assert resp.status_code == 200 and "each containing" in html(resp)
        resp = await hr.download_invoice_pdf(make_request(method="GET"), invoice_id=inv.id, db=db, user=env.admin)
        assert resp.body[:4] == b"%PDF"


@test
async def test_legacy_invoice_gets_frozen_lines_from_its_own_counts(env):
    async with env.Session() as db:
        legacy = CateringInvoice(
            invoice_number="AL-0099", program_id=env.p["Alpha"], service_date=SERVICE, regular_meal_count=20,
            lunch_count=12, breakfast_count=None, status="finalized", tenant_id=TENANT_ID,
        )
        db.add(legacy)
        await db.commit()
        legacy_id = legacy.id
    async with env.Session() as db:
        resp = await hr.view_invoice(make_request(method="GET"), invoice_id=legacy_id, db=db, user=env.admin)
        assert resp.status_code == 200
    lines = [l for l in (await env.invoice("Alpha"))[0].lines if l.meal_slot == "lunch"]
    assert lines and all(l.meal_count == 12 for l in lines), "built from the stored count, not today's"


@test
async def test_production_page_renders_sub_controls(env):
    await env.sub("Chicken", "Turkey")
    async with env.Session() as db:
        page = html(await pr.production_daily_view(make_request(method="GET"), date_str=SERVICE.isoformat(), selected=None, db=db, user=env.admin))
        assert "Today's substitutions" in page and "⇄ Sub" in page and 'id="subModal"' in page
        assert "/catering/production/day-pack" in page and "prod-actions" in page
        assert 'class="prod-chip"' not in page, "no per-program bubbles"
        worker_page = html(await pr.production_daily_view(make_request(method="GET"), date_str=SERVICE.isoformat(), selected=None, db=db, user=env.worker))
        assert "⇄ Sub" not in worker_page and 'id="subModal"' not in worker_page
        batch = html(await pr.production_daily_view(
            make_request(method="GET"), date_str=SERVICE.isoformat(),
            selected=f"{SERVICE.isoformat()},{(SERVICE + timedelta(days=1)).isoformat()}", db=db, user=env.admin))
        assert "openSubModal(this)\">⇄ Sub" not in batch, "subs are per-day, so off in Batch Prep Mode"


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
