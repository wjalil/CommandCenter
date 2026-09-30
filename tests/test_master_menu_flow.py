"""
Master Menu upload + publish — end-to-end tests.

Uses the real October_2026_Master_Menu.csv at the repo root, a throwaway in-memory
SQLite database, and the real endpoint functions/templates (same harness style as
test_catering_delivery_flow.py). No server and no pytest required:

    .venv\\Scripts\\python.exe tests\\test_master_menu_flow.py
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import asyncio
import io
import json
import re
import traceback
import warnings
from datetime import date
from html import unescape
from urllib.parse import urlencode

from fastapi import UploadFile
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
    CACFPAgeGroup, CACFPComponentType, FoodComponent, CateringMonthlyMenu, CateringMenuDay,
    CateringMasterMenu, CateringMasterMenuDay, CateringProgram, MenuDayComponent, DailyManifestItem,
)
from app.schemas.catering import CateringProgramCreate, BulkComponentsRequest
from app.crud.catering import program as program_crud
from app.api.catering import master_menu_routes as mr
from app.api.catering import monthly_menu_routes as mmr
from app.api.catering import production_routes as pr
from app.api.catering import html_routes as hr
from app.services.catering import master_menu_import as mmi
from app.services.catering.master_menu_publish import load_master_menu, publish_master_menu

warnings.filterwarnings("ignore")

TENANT_ID = 1
CSV_PATH = os.path.join(ROOT, "October_2026_Master_Menu.csv")
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def make_request(form=None, query=None, method="POST"):
    payload = urlencode(form or {}, doseq=True).encode()
    scope = {
        "type": "http", "method": method, "path": "/",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        "query_string": urlencode(query or {}).encode(), "session": {}, "state": {},
    }

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    req = Request(scope, receive)
    req.state.tenant_id = TENANT_ID
    return req


def html(resp) -> str:
    return resp.body.decode("utf-8")


def hidden(page: str, name: str) -> str:
    m = re.search(r'name="%s" value="([^"]*)"' % re.escape(name), page)
    assert m, f"hidden field {name} not in page"
    return unescape(m.group(1))


class Env:
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
            self.admin = User(name="Admin", pin_code="1000", role="admin", tenant_id=TENANT_ID, is_active=True)
            db.add(self.admin)
            # Existing components: "Tortillas" should absorb the sheet's "Tortilla"; "Crackers" is exact
            db.add_all([
                FoodComponent(name="Tortillas", component_type_id=3, default_portion_oz=1, tenant_id=TENANT_ID),
                FoodComponent(name="Crackers", component_type_id=3, default_portion_oz=0.5, tenant_id=TENANT_ID),
                FoodComponent(name="Cheese Sticks", component_type_id=2, default_portion_oz=1, tenant_id=TENANT_ID),
            ])
            await db.commit()

        self.p = {}
        for name, days, meals in [
            ("Alpha", WEEKDAYS, ["Breakfast", "Lunch"]),
            ("Bravo", ["Monday", "Wednesday", "Friday"], ["Lunch", "Snack"]),
            ("Charlie", WEEKDAYS, ["Breakfast", "Lunch", "PM Snack"]),
        ]:
            async with self.Session() as db:
                program = await program_crud.create_program(db, CateringProgramCreate(
                    name=name, client_name=f"{name} Director", age_group_id=4, total_children=20,
                    invoice_prefix=name[:2].upper(), service_days=days, meal_types_required=meals,
                    start_date=date(2026, 9, 1), tenant_id=TENANT_ID,
                ))
                self.p[name] = program.id
        return self

    async def close(self):
        await self.engine.dispose()

    async def upload(self, name="Standard", data=None):
        data = data or open(CSV_PATH, "rb").read()
        async with self.Session() as db:
            upload = UploadFile(file=io.BytesIO(data), filename="October_2026_Master_Menu.csv")
            resp = await mr.master_menu_upload(make_request(), file=upload, name=name, db=db, user=self.admin)
            assert resp.status_code == 200, html(resp)
            return html(resp)

    async def confirm(self, page, extra=None):
        form = {
            "sheet_json": hidden(page, "sheet_json"),
            "name": hidden(page, "name"),
            "source_filename": hidden(page, "source_filename"),
        }
        form.update(extra or {})
        async with self.Session() as db:
            return await mr.master_menu_import_confirm(make_request(form), db=db, user=self.admin)

    async def master(self):
        async with self.Session() as db:
            return (await db.execute(
                select(CateringMasterMenu).options(
                    selectinload(CateringMasterMenu.days).selectinload(CateringMasterMenuDay.components)
                )
            )).scalars().first()

    async def publish(self, names, **opts):
        m = await self.master()
        form = {"program_ids": [self.p[n] for n in names]}
        form.update({k: "1" for k, v in opts.items() if v})
        if "closed_as_holidays" not in opts:
            form["closed_as_holidays"] = "1"
        async with self.Session() as db:
            resp = await mr.master_menu_publish(make_request(form), master_id=m.id, db=db, user=self.admin)
            assert resp.status_code == 200
            return html(resp)

    async def program_menu(self, name):
        async with self.Session() as db:
            return (await db.execute(
                select(CateringMonthlyMenu)
                .where(CateringMonthlyMenu.program_id == self.p[name], CateringMonthlyMenu.month == 10)
                .options(
                    selectinload(CateringMonthlyMenu.menu_days)
                        .selectinload(CateringMenuDay.components)
                        .selectinload(MenuDayComponent.food_component)
                )
            )).scalars().first()

    async def day_names(self, name, d, slot=None):
        menu = await self.program_menu(name)
        day = next((x for x in menu.menu_days if x.service_date == d), None)
        if not day:
            return None
        return sorted(
            (c.meal_slot, c.food_component.name) for c in day.components if slot is None or c.meal_slot == slot
        )


# ==================== tests ====================

async def test_parse_splits_and_detects_columns(env):
    sheet = mmi.parse_csv(open(CSV_PATH).read(), ["Tortillas"])
    assert (sheet.month, sheet.year) == (10, 2026)
    assert [c.slot for c in sheet.columns] == ["breakfast", "breakfast", "lunch", "lunch", "lunch", "pm_snack"]
    assert [c.type_hint for c in sheet.columns] == [None, "Fruit", None, "Vegetable", "Fruit", None]
    assert len(sheet.rows) == 22
    by_date = {r.service_date: r for r in sheet.rows}
    assert by_date["2026-10-12"].closed_reason == "OFF"
    assert by_date["2026-10-02"].cells[2] == ["Chicken Nuggets", "Mashed Potatoes", "Bread"]
    assert by_date["2026-10-06"].cells[5] == ["Carrot & Cucumber Sticks", "Hummus"]
    assert mmi.guess_type("Orange Chicken") == "Meat/Meat Alternate"
    assert mmi.guess_type("Cornbread") == "Grain"
    assert mmi.guess_type("Yogurt") == "Meat/Meat Alternate"


async def test_preview_shows_matches(env):
    page = await env.upload()
    assert "October 2026" in page
    # plural match counts as matched (not new); close spelling is suggested
    sheet = mmi.Sheet.from_json_dict(json.loads(hidden(page, "sheet_json")))
    matches = mmi.match_tokens(sheet, [(1, "Tortillas"), (2, "Crackers"), (3, "Cheese Sticks")])
    assert matches[mmi.match_key("Tortilla")].status == "matched"
    assert matches[mmi.match_key("Cheese Stick")].status == "matched"
    assert matches[mmi.match_key("Chicken Tacos")].status == "new"


async def test_confirm_creates_master_and_components(env):
    page = await env.upload()
    resp = await env.confirm(page)
    assert resp.status_code == 303
    m = await env.master()
    assert (m.month, m.year, m.status) == (10, 2026, "draft")
    assert len(m.days) == 22 and sum(d.is_closed for d in m.days) == 1
    async with env.Session() as db:
        names = {c.name for c in (await db.execute(select(FoodComponent))).scalars().all()}
    assert "Tortilla" not in names and "Tortillas" in names  # reused, not duplicated
    assert {"Chicken Tacos", "Mashed Potatoes", "Carrot & Cucumber Sticks"} <= names
    # the view renders
    async with env.Session() as db:
        view = await mr.master_menu_view(make_request(method="GET", query={"imported": "1"}), master_id=m.id, db=db, user=env.admin)
        assert "Publish to programs" in html(view)
        lst = await mr.master_menus_list(make_request(method="GET"), db=db, user=env.admin)
        assert "October 2026" in html(lst)


async def test_confirm_uses_preview_decisions_and_cell_edits(env):
    page = await env.upload()
    sheet = mmi.Sheet.from_json_dict(json.loads(hidden(page, "sheet_json")))
    r = next(i for i, row in enumerate(sheet.rows) if row.service_date == "2026-10-01")
    key = mmi.match_key("Chicken Tacos")
    resp = await env.confirm(page, {
        f"tok__{r}__2": "Chicken Taco Filling; Tortillas",          # user fixed the lunch cell
        "key__0": mmi.match_key("Chicken Taco Filling"),
        "choice__0": "new", "newname__0": "Taco Chicken", "newtype__0": "2",
        "key__1": key, "choice__1": "c:2",                           # map Chicken Tacos -> Crackers (silly, but explicit)
    })
    assert resp.status_code == 303
    m = await env.master()
    d = next(d for d in m.days if d.service_date == date(2026, 10, 1))
    async with env.Session() as db:
        comps = {c.id: c for c in (await db.execute(select(FoodComponent))).scalars().all()}
    lunch = [comps[c.component_id].name for c in d.components if c.meal_slot == "lunch"]
    assert lunch[:2] == ["Taco Chicken", "Tortillas"], lunch
    d27 = next(d for d in m.days if d.service_date == date(2026, 10, 27))
    assert "Crackers" in [comps[c.component_id].name for c in d27.components if c.meal_slot == "lunch"]


async def test_duplicate_master_needs_replace(env):
    page = await env.upload()
    assert (await env.confirm(page)).status_code == 303
    first = await env.master()
    page = await env.upload()
    resp = await env.confirm(page)
    assert resp.status_code == 200 and "already exists" in html(resp)
    resp = await env.confirm(page, {"replace_existing": "1"})
    assert resp.status_code == 303
    again = await env.master()
    assert again.id == first.id and len(again.days) == 22


async def test_publish_respects_service_days_meal_types_and_closures(env):
    await env.confirm(await env.upload())
    page = await env.publish(["Alpha", "Bravo"])
    assert "Publish results" in page

    alpha = await env.program_menu("Alpha")
    assert alpha.master_menu_id and len(alpha.menu_days) == 21  # 22 rows minus the OFF day
    slots = {c.meal_slot for d in alpha.menu_days for c in d.components}
    assert slots == {"breakfast", "lunch"}
    assert await env.day_names("Alpha", date(2026, 10, 12)) is None
    async with env.Session() as db:
        p = (await db.execute(select(CateringProgram).where(CateringProgram.id == env.p["Alpha"])
                              .options(selectinload(CateringProgram.holidays)))).scalar_one()
        assert [h.holiday_date for h in p.holidays] == [date(2026, 10, 12)]

    bravo = await env.program_menu("Bravo")
    assert {d.service_date.strftime("%A") for d in bravo.menu_days} == {"Monday", "Wednesday", "Friday"}
    # Bravo takes "Snack": the sheet only has PM Snack, so it maps across
    assert await env.day_names("Bravo", date(2026, 10, 2), "snack") == [("snack", "Cheese Sticks"), ("snack", "Crackers")]

    # Production reads the published menus with no changes
    async with env.Session() as db:
        data = await pr._build_production_data(db, TENANT_ID, date(2026, 10, 1))
    names = {c["name"] for c in data["prep_components"]} | {c["name"] for c in data["produce_components"]}
    assert {"Chicken Tacos", "Mini Croissant"} <= names, names


async def test_republish_keeps_hand_edited_days(env):
    await env.confirm(await env.upload())
    await env.publish(["Alpha"])
    alpha = await env.program_menu("Alpha")
    async with env.Session() as db:
        crackers = (await db.execute(select(FoodComponent).where(FoodComponent.name == "Crackers"))).scalar_one()
        await mmr.bulk_assign_components(make_request(), menu_id=alpha.id, data=BulkComponentsRequest(menu_days=[{
            "service_date": "2026-10-05", "replace_existing": True,
            "components": [{"component_id": crackers.id, "meal_slot": "lunch"}],
        }]), db=db)
    assert await env.day_names("Alpha", date(2026, 10, 5)) == [("lunch", "Crackers")]

    m = await env.master()
    async with env.Session() as db:
        master = await load_master_menu(db, m.id, TENANT_ID)
        [res] = await publish_master_menu(db, master, [env.p["Alpha"]])
    assert (res.days_customized_kept, res.days_written) == (1, 20)
    assert await env.day_names("Alpha", date(2026, 10, 5)) == [("lunch", "Crackers")]
    async with env.Session() as db:
        cal = html(await hr.menu_calendar_view(make_request(method="GET"), menu_id=alpha.id, db=db, user=env.admin))
    assert "Published from the" in cal and cal.count('title="Edited by hand') == 1

    await env.publish(["Alpha"], overwrite_customized=True)
    assert ("lunch", "BBQ Chicken") in await env.day_names("Alpha", date(2026, 10, 5))


async def test_snack_and_pm_snack_columns_stay_separate(env):
    csv_data = (
        "Date,Day,Breakfast,Lunch,Snack,PM Snack\n"
        "10/1/2026,Thursday,Muffin,Cheese Pizza,Apple + Crackers,Yogurt + Pineapple\n"
        "10/2/2026,Friday,Bagel,BBQ Chicken w/ Rice,Cheese Stick,Hummus + Crackers\n"
    ).encode()
    await env.confirm(await env.upload(data=csv_data))
    await env.publish(["Bravo", "Charlie"])
    # Bravo takes Snack -> the Snack column (not PM Snack, now that the sheet has both)
    assert await env.day_names("Bravo", date(2026, 10, 2)) == [
        ("lunch", "BBQ Chicken"), ("lunch", "Rice"), ("snack", "Cheese Sticks"),
    ]
    # Charlie takes PM Snack -> the PM Snack column only
    assert await env.day_names("Charlie", date(2026, 10, 1), "pm_snack") == [("pm_snack", "Pineapple"), ("pm_snack", "Yogurt")]
    assert await env.day_names("Charlie", date(2026, 10, 1), "snack") == []


async def _set_day(env, program, day, comps):
    """Hand-edit one program day the way the calendar popup saves it: [(slot, name), ...],
    sort_order numbered from 0 within each meal."""
    menu = await env.program_menu(program)
    async with env.Session() as db:
        by_name = {c.name: c.id for c in (await db.execute(select(FoodComponent))).scalars().all()}
        per_slot = {}
        payload = []
        for slot, name in comps:
            payload.append({"component_id": by_name[name], "meal_slot": slot, "sort_order": per_slot.get(slot, 0)})
            per_slot[slot] = per_slot.get(slot, 0) + 1
        await mmr.bulk_assign_components(make_request(), menu_id=menu.id, data=BulkComponentsRequest(menu_days=[{
            "service_date": day.isoformat(), "replace_existing": True, "components": payload,
        }]), db=db)


async def test_reordered_items_keep_their_order(env):
    await env.confirm(await env.upload())
    await env.publish(["Alpha"])
    d = date(2026, 10, 5)
    # Rice moved above BBQ Chicken in lunch, after two breakfast items
    await _set_day(env, "Alpha", d, [
        ("breakfast", "Bagel"), ("breakfast", "Apple"),
        ("lunch", "Rice"), ("lunch", "BBQ Chicken"), ("lunch", "Mixed Vegetables"),
    ])
    menu = await env.program_menu("Alpha")
    day = next(x for x in menu.menu_days if x.service_date == d)
    lunch = [c.food_component.name for c in sorted(day.components, key=lambda c: c.sort_order) if c.meal_slot == "lunch"]
    assert lunch == ["Rice", "BBQ Chicken", "Mixed Vegetables"], lunch
    # and the calendar page renders them in that order after a refresh
    async with env.Session() as db:
        page = html(await hr.menu_calendar_view(make_request(method="GET"), menu_id=menu.id, db=db, user=env.admin))
    day_json = json.loads(re.search(r"menuDayComponents\s*=\s*(\{.*?\});", page, re.S).group(1)) if "menuDayComponents =" in page else None
    if day_json:
        assert [c["name"] for c in day_json[d.isoformat()]["lunch"]] == lunch


def _packaging(data, program_name, slot):
    pd = next(p for p in data["programs_data"] if p["program"].name == program_name)
    pkg = next(p for p in pd["packaging"] if p["slot"] == slot)
    return [c["name"] for c in pkg["components"]]


async def test_pm_snack_packaging_lists_items_not_slot_name(env):
    await env.confirm(await env.upload())
    await env.publish(["Charlie"])
    # fruit-only PM snack: the fruit is the snack
    await _set_day(env, "Charlie", date(2026, 10, 2), [("lunch", "Cheese Pizza"), ("pm_snack", "Pineapple")])
    # snack entered under "Snack" for a program set up for "PM Snack"
    await _set_day(env, "Charlie", date(2026, 10, 5), [("lunch", "Cheese Pizza"), ("snack", "Crackers")])
    async with env.Session() as db:
        assert _packaging(await pr._build_production_data(db, TENANT_ID, date(2026, 10, 1)), "Charlie", "pm_snack") == ["Yogurt"]
        assert _packaging(await pr._build_production_data(db, TENANT_ID, date(2026, 10, 2)), "Charlie", "pm_snack") == ["Pineapple"]
        assert _packaging(await pr._build_production_data(db, TENANT_ID, date(2026, 10, 5)), "Charlie", "pm_snack") == ["Crackers"]


async def test_checking_real_snack_item_replaces_placeholder_line(env):
    d = date(2026, 10, 2)
    async with env.Session() as db:
        await pr._sync_manifest_component(db, TENANT_ID, env.p["Charlie"], d, "pm_snack", "PM Snack", True)
    async with env.Session() as db:
        await pr._sync_manifest_component(db, TENANT_ID, env.p["Charlie"], d, "pm_snack", "Pineapple", True)
    async with env.Session() as db:
        labels = [i.label for i in (await db.execute(select(DailyManifestItem))).scalars().all()]
    assert labels == ["Pineapple"], labels


async def test_locked_menus_are_skipped(env):
    await env.confirm(await env.upload())
    await env.publish(["Charlie"])
    async with env.Session() as db:
        menu = (await db.execute(select(CateringMonthlyMenu).where(CateringMonthlyMenu.program_id == env.p["Charlie"]))).scalar_one()
        menu.status = "finalized"
        await db.commit()
    page = await env.publish(["Charlie"], overwrite_customized=True)
    assert "Skipped — locked" in page
    page = await env.publish(["Charlie"], include_locked=True)
    assert "Updated" in page
    charlie = await env.program_menu("Charlie")
    assert {c.meal_slot for d in charlie.menu_days for c in d.components} == {"breakfast", "lunch", "pm_snack"}


async def test_bad_files_are_rejected(env):
    async with env.Session() as db:
        for data, fname, msg in [
            (b"Breakfast,Lunch\nMuffin,Pizza\n", "x.csv", "No &#39;Date&#39; column"),
            (b"Date,Colour\n10/1/2026,Blue\n", "x.csv", "No meal columns"),
            (b"PK\x03\x04", "menu.xlsx", "save the spreadsheet as CSV"),
        ]:
            resp = await mr.master_menu_upload(
                make_request(), file=UploadFile(file=io.BytesIO(data), filename=fname), name="Standard", db=db, user=env.admin,
            )
            assert resp.status_code == 400 and msg in html(resp), html(resp)


TESTS = [
    test_parse_splits_and_detects_columns,
    test_preview_shows_matches,
    test_confirm_creates_master_and_components,
    test_confirm_uses_preview_decisions_and_cell_edits,
    test_duplicate_master_needs_replace,
    test_publish_respects_service_days_meal_types_and_closures,
    test_republish_keeps_hand_edited_days,
    test_snack_and_pm_snack_columns_stay_separate,
    test_reordered_items_keep_their_order,
    test_pm_snack_packaging_lists_items_not_slot_name,
    test_checking_real_snack_item_replaces_placeholder_line,
    test_locked_menus_are_skipped,
    test_bad_files_are_rejected,
]


async def with_env(fn):
    env = await Env().setup()
    try:
        await fn(env)
    finally:
        await env.close()


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
