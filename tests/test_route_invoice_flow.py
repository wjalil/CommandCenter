"""
Route paperwork flow — Produce card on the invoice, editable invoices + supplies,
release, and the one-button route print pack (invoices last-to-first, manifest last).

Same harness as test_subs_ddi_flow.py (its Env is reused). Run:

    .venv\\Scripts\\python.exe tests\\test_route_invoice_flow.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_subs_ddi_flow import Env, make_request, html, body_json, SERVICE, TENANT_ID  # noqa: E402 (sets up the env)

import asyncio
import traceback

from sqlalchemy.future import select

from app.models.catering import (
    CateringMenuDay, CateringMonthlyMenu, DailyManifestItem, DailyManifestStop, MenuDayComponent,
)
from app.api.catering import production_routes as pr
from app.api.catering import html_routes as hr
from app.services.catering import ddi

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


async def produce(env, program, items):
    async with env.Session() as db:
        await pr.save_supply_selection(make_request({
            "date": SERVICE.isoformat(), "program_id": env.p[program], "supply": "produce", "items": items,
        }), db=db, user=env.worker)


async def add_to_menu(env, program, comp, slot):
    async with env.Session() as db:
        day = (await db.execute(select(CateringMenuDay).join(CateringMonthlyMenu).where(
            CateringMonthlyMenu.program_id == env.p[program]))).scalar_one()
        db.add(MenuDayComponent(menu_day_id=day.id, component_id=env.c[comp], meal_slot=slot, sort_order=50))
        await db.commit()


async def the_invoice(env, program):
    invs = await env.invoice(program)
    assert len(invs) == 1, f"{program}: {len(invs)} invoices"
    return invs[0]


async def editor_payload(env, program):
    """What the editor would post back unchanged, as plain dicts."""
    inv = await the_invoice(env, program)
    meals = [{
        "slot": m["slot"], "is_vegan": m["is_vegan"], "meal_count": m["meal_count"],
        "lines": [{
            "component_type": l["component_type"], "item_name": l["item_name"], "portion_qty": l["portion_qty"],
            "portion_unit": l["portion_unit"], "substituted_for": l["substituted_for"] or "",
            "substitution_reason": l["reason"] or "", "is_auto": l["is_auto"],
        } for l in m["lines"]],
    } for m in ddi.invoice_meals(inv)]
    return {"meals": meals, "supplies": ddi.invoice_supplies(inv)}


async def save(env, program, payload):
    inv = await the_invoice(env, program)
    async with env.Session() as db:
        return await pr.route_invoice_save(make_request(payload), invoice_id=inv.id, db=db, user=env.admin)


async def reset(env, program):
    inv = await the_invoice(env, program)
    async with env.Session() as db:
        return await pr.route_invoice_reset(make_request(), invoice_id=inv.id, db=db, user=env.admin)


async def view(env, program):
    inv = await the_invoice(env, program)
    async with env.Session() as db:
        return html(await hr.view_invoice(make_request(method="GET"), invoice_id=inv.id, db=db, user=env.admin))


async def route_page(env, route):
    await env.build_manifests()
    m = await env.manifest(route)
    async with env.Session() as db:
        return await pr.route_invoices(make_request(method="GET"), manifest_id=m.id, db=db, user=env.admin)


async def print_pack(env, route, scope="cacfp"):
    m = await env.manifest(route)
    async with env.Session() as db:
        return html(await pr.route_print_pack(make_request(method="GET"), manifest_id=m.id, scope=scope, db=db, user=env.admin))


def items(lines):
    return [l.item_name for l in lines]


# ==================== 1) Produce card -> invoice ====================

@test
async def test_produce_card_replaces_menu_fruit_at_every_meal(env):
    await add_to_menu(env, "Alpha", "Apple", "lunch")
    await add_to_menu(env, "Alpha", "Apple", "breakfast")
    await env.generate()
    assert "Apple" in items(await env.lines("Alpha")), "no pick yet -> the menu's fruit"

    await produce(env, "Alpha", ["Banana", "Orange"])
    await env.generate()
    for slot in ("lunch", "breakfast"):
        fruit = [l for l in await env.lines("Alpha", slot) if l.component_type == "Fruit"]
        assert len(fruit) == 1, (slot, items(fruit))
        assert fruit[0].item_name == "Banana, Orange" and fruit[0].substituted_for == "Apple", slot
    page = await view(env, "Alpha")
    assert "Banana, Orange served in place of Apple" in page


@test
async def test_picking_the_menus_fruit_is_not_a_sub(env):
    await add_to_menu(env, "Alpha", "Apple", "lunch")
    await produce(env, "Alpha", ["Apple"])
    await env.generate()
    fruit = [l for l in await env.lines("Alpha") if l.component_type == "Fruit"]
    assert [l.item_name for l in fruit] == ["Apple"] and fruit[0].substituted_for is None


@test
async def test_opening_a_draft_shows_the_latest_produce_pick(env):
    """The reported bug: a draft built earlier kept the old fruit when viewed."""
    await add_to_menu(env, "Alpha", "Apple", "lunch")
    await env.generate()
    await produce(env, "Alpha", ["Pear"])
    assert "Pear served in place of Apple" in await view(env, "Alpha"), "no regenerate needed"


# ==================== 2) editable invoices ====================

@test
async def test_hand_edits_stick_until_reset(env):
    await env.generate()
    payload = await editor_payload(env, "Alpha")
    lunch = next(m for m in payload["meals"] if m["slot"] == "lunch")
    lunch["meal_count"] = 17
    lunch["lines"][0]["item_name"] = "Herb Chicken"
    lunch["lines"].append({"component_type": "Other", "item_name": "Hot sauce cups", "portion_qty": 1, "portion_unit": "ea"})
    resp = await save(env, "Alpha", payload)
    assert resp.status_code == 200, html(resp)
    assert body_json(resp)["meals_changed"] is True

    inv = await the_invoice(env, "Alpha")
    assert inv.edited_at is not None and inv.edited_by_user_id == env.admin.id
    assert inv.lunch_count == 17, "the served headcount lives on the invoice"
    lunch_lines = await env.lines("Alpha")
    assert lunch_lines[0].item_name == "Herb Chicken" and all(l.meal_count == 17 for l in lunch_lines)
    assert "Hot sauce cups" in items(lunch_lines)

    # Kitchen changes no longer overwrite the edited invoice...
    await env.count("Alpha", "lunch", 12)
    await env.generate()
    assert (await the_invoice(env, "Alpha")).lunch_count == 17
    assert "Herb Chicken" in await view(env, "Alpha")

    # ...until it's reset from the kitchen
    assert (await reset(env, "Alpha")).status_code == 200
    inv = await the_invoice(env, "Alpha")
    assert inv.edited_at is None and inv.lunch_count == 12
    assert items(await env.lines("Alpha"))[0] == "Chicken"


@test
async def test_saving_unchanged_meals_keeps_following_the_kitchen(env):
    await env.generate()
    payload = await editor_payload(env, "Alpha")
    payload["supplies"] = [{"item_name": "Sporks", "qty": 30}]
    resp = await save(env, "Alpha", payload)
    assert body_json(resp)["meals_changed"] is False
    assert (await the_invoice(env, "Alpha")).edited_at is None, "adding supplies alone doesn't freeze the meals"
    await env.count("Alpha", "lunch", 15)
    await env.generate()
    inv = await the_invoice(env, "Alpha")
    assert inv.lunch_count == 15 and ddi.invoice_supplies(inv) == [{"item_name": "Sporks", "qty": 30}], "supplies survive rebuilds"


@test
async def test_removing_a_meal_and_adding_one(env):
    await env.generate()
    payload = await editor_payload(env, "Alpha")
    payload["meals"] = [m for m in payload["meals"] if m["slot"] != "breakfast"]
    payload["meals"].append({"slot": "pm_snack", "is_vegan": False, "meal_count": 20,
                             "lines": [{"component_type": "Grain", "item_name": "Crackers", "portion_qty": 0.5, "portion_unit": "oz"}]})
    assert (await save(env, "Alpha", payload)).status_code == 200
    inv = await the_invoice(env, "Alpha")
    assert inv.breakfast_count is None and inv.pm_snack_count == 20
    assert [m["slot"] for m in ddi.invoice_meals(inv)] == ["lunch", "pm_snack"], "serving order"


@test
async def test_bad_edits_are_rejected(env):
    await env.generate()
    payload = await editor_payload(env, "Alpha")
    payload["meals"][0]["meal_count"] = "2.5"
    assert (await save(env, "Alpha", payload)).status_code == 400
    payload = await editor_payload(env, "Alpha")
    payload["supplies"] = [{"item_name": "Spoons", "qty": 0}]
    assert (await save(env, "Alpha", payload)).status_code == 400
    payload = await editor_payload(env, "Alpha")
    payload["meals"][0]["lines"][0]["portion_qty"] = "lots"
    assert (await save(env, "Alpha", payload)).status_code == 400
    assert (await the_invoice(env, "Alpha")).edited_at is None, "nothing saved"


# ==================== supplies ====================

@test
async def test_supplies_print_separately_and_reach_the_manifest(env):
    await env.build_manifests()
    await env.generate()
    payload = await editor_payload(env, "Alpha")
    payload["supplies"] = [{"item_name": "Sporks", "qty": 30}, {"item_name": "Napkins", "qty": 40}]
    await save(env, "Alpha", payload)

    inv = await the_invoice(env, "Alpha")
    assert ddi.total_meals(inv) == 40, "supplies are never counted as meals (20 breakfast + 20 lunch)"
    page = await view(env, "Alpha")
    assert "SUPPLIES" in page and "billed separately" in page and "Sporks" in page
    async with env.Session() as db:
        pdf = await hr.download_invoice_pdf(make_request(method="GET"), invoice_id=inv.id, db=db, user=env.admin)
    assert pdf.body[:4] == b"%PDF", "supplies section renders in the PDF too"

    async with env.Session() as db:
        labels = (await db.execute(
            select(DailyManifestItem.label).join(DailyManifestStop)
            .where(DailyManifestStop.program_id == env.p["Alpha"], DailyManifestItem.source == "supplies")
        )).scalars().all()
    assert sorted(labels) == ["Napkins × 40", "Sporks × 30"], labels

    payload["supplies"] = [{"item_name": "Sporks", "qty": 25}]
    await save(env, "Alpha", payload)
    async with env.Session() as db:
        labels = (await db.execute(
            select(DailyManifestItem.label).join(DailyManifestStop)
            .where(DailyManifestStop.program_id == env.p["Alpha"], DailyManifestItem.source == "supplies")
        )).scalars().all()
    assert labels == ["Sporks × 25"], "manifest follows the invoice"


# ==================== release + lock ====================

@test
async def test_released_invoice_cannot_be_edited_or_reset(env):
    await env.generate()
    await env.release("R1")
    payload = await editor_payload(env, "Alpha")
    resp = await save(env, "Alpha", payload)
    assert resp.status_code == 409 and "Reopen" in body_json(resp)["error"]
    assert (await reset(env, "Alpha")).status_code == 409
    await env.reopen("R1")
    assert (await save(env, "Alpha", payload)).status_code == 200


@test
async def test_edited_invoice_is_what_gets_locked(env):
    await env.generate()
    payload = await editor_payload(env, "Alpha")
    payload["meals"][0]["meal_count"] = 9
    await save(env, "Alpha", payload)
    await env.release("R1")
    inv = await the_invoice(env, "Alpha")
    assert inv.status == "finalized" and inv.breakfast_count == 9, "release must not rebuild over hand edits"


# ==================== route Invoices page ====================

@test
async def test_route_invoices_page_draft_then_released(env):
    resp = await route_page(env, "R1")
    assert resp.status_code == 200
    page = html(resp)
    assert page.index("Alpha") < page.index("Bravo"), "driving order"
    assert page.count('class="ie"') == 2, "one editor per stop"
    assert "Release R1 for Print" in page and "Live from kitchen" in page
    assert "+ Sporks" in page

    m = await env.manifest("R1")
    async with env.Session() as db:
        here = f"/catering/production/manifest/{m.id}/invoices"
        resp = await pr.manifest_release(make_request(), manifest_id=m.id, next=here, db=db, user=env.admin)
        assert resp.headers["location"] == here, "release from the Invoices step comes back to it"
        evil = await pr.manifest_reopen(make_request(), manifest_id=m.id, next="//evil.example", db=db, user=env.admin)
        assert evil.headers["location"].startswith("/catering/production/manifest/builder")
        await pr.manifest_release(make_request(), manifest_id=m.id, next=here, db=db, user=env.admin)

    page = html(await route_page(env, "R1"))
    assert 'class="ie"' not in page and "🔒 Locked" in page
    assert "Print Route Pack" in page and "print-pack?autoprint=1" in page


@test
async def test_manifest_builder_points_to_invoices_then_print(env):
    async with env.Session() as db:
        page = html(await pr.manifest_builder(make_request(method="GET"), date_str=SERVICE.isoformat(), db=db, user=env.admin))
    assert "Next: Build R1 Invoices" in page and "/release\" method" not in page
    await env.release("R1")
    async with env.Session() as db:
        page = html(await pr.manifest_builder(make_request(method="GET"), date_str=SERVICE.isoformat(), db=db, user=env.admin))
    assert "Print Route Pack" in page


# ==================== one print button ====================

@test
async def test_print_pack_is_last_stop_first_then_manifest(env):
    async with env.Session() as db:
        from app.models.catering import CateringProgram
        charlie = await db.get(CateringProgram, env.p["Charlie"])
        charlie.route_code, charlie.route_stop_order = "R1", 3  # non-CACFP stop on the same route
        await db.commit()
    await env.release("R1")
    page = await print_pack(env, "R1")

    alpha, bravo, manifest = page.index("1 Alpha St"), page.index("1 Bravo St"), page.index("Daily Manifest")
    assert bravo < alpha < manifest, "stop 2, stop 1, then the manifest — face-up stack reads manifest, 1, 2"
    assert page.count("DAILY DELIVERY INVOICE") == 2, "CACFP only by default"
    assert "Driver signature" in page and "dm-stops" in page, "same manifest sheet as View Manifest"
    assert "not released" not in page

    everyone = await print_pack(env, "R1", scope="all")
    assert everyone.count("DAILY DELIVERY INVOICE") == 3
    assert everyone.index("1 Charlie St") < everyone.index("1 Bravo St"), "stop 3 prints first"


@test
async def test_print_pack_warns_on_draft_and_generic_fruit(env):
    await env.build_manifests()
    page = await print_pack(env, "R1")
    assert "released yet" in page and "DRAFT" in page
    assert "Seasonal Fruit" in page and "Produce card" in page


@test
async def test_driver_manifest_view_unchanged(env):
    await env.release("R1")
    async with env.Session() as db:
        page = html(await pr.driver_manifest_detail(make_request(method="GET"), route_code="R1",
                                                    date_str=SERVICE.isoformat(), db=db, user=env.admin))
    assert "Print Manifest" in page and "Driver signature" in page and "Alpha" in page and "dmToggleItem" in page


# ==================== month-end audit ====================

@test
async def test_invoices_list_shows_served_headcount(env):
    await env.generate()
    payload = await editor_payload(env, "Alpha")
    next(m for m in payload["meals"] if m["slot"] == "lunch")["meal_count"] = 17
    payload["supplies"] = [{"item_name": "Sporks", "qty": 30}]
    await save(env, "Alpha", payload)
    async with env.Session() as db:
        page = html(await hr.invoices_list(make_request(method="GET"), db=db, user=env.admin))
    alpha = page[page.index("Alpha"):page.index("Bravo")]
    assert "Served this month" in alpha and "37 meals" in alpha, "20 breakfast + 17 lunch (hand-edited)"
    assert "Lunch <strong>17</strong>" in alpha
    assert "Sporks &times; 30" in alpha


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
