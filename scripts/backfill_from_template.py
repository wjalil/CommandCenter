"""
Backfill a date range of menu days for one or more target programs by cloning
menu items from a template program's menu, and synthesizing a CACFP-eligible
breakfast where the target program requires breakfast and the template day
doesn't already have one there.

Why: some programs' calendars have gaps (menu never got built for those days).
Rather than manually re-picking every meal, this clones an already-built,
known-good day (the template program) into each target program's matching
date - only for the meal slots the target program actually requires - and
builds a simple, CACFP-compliant breakfast (milk + grain + fruit/veg, plus a
vegan version if the target program tracks vegan headcount) by reusing
whatever milk/fruit the template day already uses at lunch, so it stays
thematically consistent with the rest of that day's menu.

Idempotent / additive only: never overwrites or duplicates a slot+component
that's already on the target day. Safe to re-run.

Safe by default: DRY RUN unless --execute is passed.

Usage:
    python scripts/backfill_from_template.py \\
        --template-program-name "Amazing Explorers" \\
        --target-program-names "Dayhab,Prevo,Rockaway" \\
        --start-date 2026-09-01 --end-date 2026-09-09

    (add --execute once the dry-run plan looks right)
"""

import asyncio
import sys
import os
import argparse
from datetime import date, timedelta

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.db import async_session
from app.models.catering import (
    CateringProgram, CateringMonthlyMenu, CateringMenuDay, MenuDayComponent, FoodComponent
)
from app.models.catering.cacfp_rules import CACFPComponentType

CLONE_SLOTS = ["lunch", "snack", "am_snack", "pm_snack"]  # breakfast handled specially
BREAKFAST_GRAIN_KEYWORDS = ["toast", "waffle", "pancake", "croissant", "muffin", "hashbrown", "cereal", "bagel"]


def normalize_meal_types(raw):
    if isinstance(raw, str):
        raw = json.loads(raw)
    return [mt.lower().replace(" ", "_") for mt in (raw or [])]


async def find_program(db, tenant_id, name_fragment):
    result = await db.execute(
        select(CateringProgram).where(
            CateringProgram.name.ilike(f"%{name_fragment}%")
        )
    )
    matches = result.scalars().all()
    if tenant_id is not None:
        matches = [p for p in matches if p.tenant_id == tenant_id]
    return matches


async def get_or_create_monthly_menu(db, program, month, year, execute):
    result = await db.execute(
        select(CateringMonthlyMenu).where(
            CateringMonthlyMenu.program_id == program.id,
            CateringMonthlyMenu.month == month,
            CateringMonthlyMenu.year == year,
            CateringMonthlyMenu.menu_type == "regular",
        ).options(selectinload(CateringMonthlyMenu.menu_days).selectinload(CateringMenuDay.components))
    )
    menu = result.scalar_one_or_none()
    if menu:
        return menu, False

    print(f"  No regular {month}/{year} monthly menu exists yet for {program.name} - "
          f"{'creating it' if execute else 'would create it'}")
    if not execute:
        return None, True

    import uuid
    menu = CateringMonthlyMenu(
        id=str(uuid.uuid4()), program_id=program.id, month=month, year=year,
        menu_type="regular", status="draft", tenant_id=program.tenant_id,
    )
    db.add(menu)
    await db.flush()
    menu.menu_days = []
    return menu, True


async def get_or_create_menu_day(db, monthly_menu, service_date, execute, plan_only_days):
    for d in monthly_menu.menu_days if monthly_menu else []:
        if d.service_date == service_date:
            return d
    if plan_only_days is not None:
        plan_only_days.add(service_date)
    if not execute or monthly_menu is None:
        return None
    import uuid
    day = CateringMenuDay(id=str(uuid.uuid4()), monthly_menu_id=monthly_menu.id, service_date=service_date)
    db.add(day)
    await db.flush()
    monthly_menu.menu_days.append(day)
    return day


async def pick_component(db, tenant_id, type_name_to_id, type_name, is_vegan=None, name_keywords=None, exclude_ids=None):
    type_id = type_name_to_id.get(type_name)
    if not type_id:
        return None
    q = select(FoodComponent).where(
        FoodComponent.tenant_id == tenant_id,
        FoodComponent.component_type_id == type_id,
    )
    if is_vegan is not None:
        q = q.where(FoodComponent.is_vegan == is_vegan)
    result = await db.execute(q)
    candidates = result.scalars().all()
    if exclude_ids:
        candidates = [c for c in candidates if c.id not in exclude_ids] or candidates
    if name_keywords:
        keyword_matches = [c for c in candidates if any(k in c.name.lower() for k in name_keywords)]
        if keyword_matches:
            candidates = keyword_matches
    if not candidates:
        return None
    candidates.sort(key=lambda c: c.name)
    return candidates[0]


async def backfill(template_name, target_names, start_date, end_date, execute):
    async with async_session() as db:
        template_matches = await find_program(db, None, template_name)
        if len(template_matches) != 1:
            print(f"Expected exactly one program matching '{template_name}', found {len(template_matches)}: "
                  f"{[p.name for p in template_matches]}")
            return
        template = template_matches[0]
        tenant_id = template.tenant_id

        ct_result = await db.execute(select(CACFPComponentType))
        type_name_to_id = {ct.name: ct.id for ct in ct_result.scalars().all()}

        target_programs = []
        for name in target_names:
            matches = await find_program(db, tenant_id, name)
            if len(matches) != 1:
                print(f"Expected exactly one program matching '{name}' in tenant {tenant_id}, "
                      f"found {len(matches)}: {[p.name for p in matches]}")
                return
            target_programs.append(matches[0])

        print(f"Template program: {template.name} ({template.id})")
        print(f"Target programs: {', '.join(p.name for p in target_programs)}")
        print(f"Date range: {start_date} to {end_date}")
        print(f"Mode: {'EXECUTE (writing changes)' if execute else 'DRY RUN (no changes written)'}\n")

        month, year = start_date.month, start_date.year
        template_menu, _ = await get_or_create_monthly_menu(db, template, month, year, execute=False)
        if not template_menu:
            print(f"No regular {month}/{year} monthly menu found for template program {template.name} - nothing to clone from.")
            return
        template_days_by_date = {d.service_date: d for d in template_menu.menu_days}

        totals = {"cloned_components": 0, "breakfast_components": 0, "skipped_existing": 0, "no_template_day": []}

        d = start_date
        while d <= end_date:
            template_day = template_days_by_date.get(d)
            if not template_day:
                totals["no_template_day"].append(d)
                d += timedelta(days=1)
                continue

            for program in target_programs:
                required = normalize_meal_types(program.meal_types_required)
                monthly_menu, _ = await get_or_create_monthly_menu(db, program, month, year, execute)
                target_day = await get_or_create_menu_day(db, monthly_menu, d, execute, plan_only_days=None)
                existing_components = {(c.meal_slot, c.component_id, c.is_vegan) for c in target_day.components} if target_day else set()

                # --- Clone lunch/snack/am_snack/pm_snack straight from template ---
                for slot in CLONE_SLOTS:
                    if slot not in required:
                        continue
                    template_slot_components = [c for c in template_day.components if c.meal_slot == slot]
                    for comp in template_slot_components:
                        key = (slot, comp.component_id, comp.is_vegan)
                        if key in existing_components:
                            totals["skipped_existing"] += 1
                            continue
                        totals["cloned_components"] += 1
                        print(f"  [{d}] {program.name} / {slot}: clone component_id={comp.component_id} "
                              f"vegan={comp.is_vegan} (qty={comp.quantity}) from {template.name}")
                        if execute and target_day:
                            db.add(MenuDayComponent(
                                menu_day_id=target_day.id, component_id=comp.component_id,
                                meal_slot=slot, is_vegan=comp.is_vegan, quantity=comp.quantity,
                                sort_order=comp.sort_order, notes=comp.notes,
                            ))

                # --- Synthesize breakfast if required and not already present ---
                if "breakfast" in required:
                    already_has_breakfast = any(c.meal_slot == "breakfast" for c in (target_day.components if target_day else []))
                    if already_has_breakfast:
                        continue

                    template_lunch_regular = [c for c in template_day.components if c.meal_slot == "lunch" and not c.is_vegan]
                    lunch_milk = None
                    lunch_fruit = None
                    lunch_vegetable = None
                    for c in template_lunch_regular:
                        ct_id = c.component_id
                        fc = await db.get(FoodComponent, ct_id)
                        if not fc:
                            continue
                        if fc.component_type_id == type_name_to_id.get("Milk") and not lunch_milk:
                            lunch_milk = fc
                        if fc.component_type_id == type_name_to_id.get("Fruit") and not lunch_fruit:
                            lunch_fruit = fc
                        if fc.component_type_id == type_name_to_id.get("Vegetable") and not lunch_vegetable:
                            lunch_vegetable = fc

                    milk = lunch_milk or await pick_component(db, tenant_id, type_name_to_id, "Milk", is_vegan=False)
                    # Prefer an actual fruit for breakfast - reusing lunch's savory vegetable/sauce
                    # (e.g. marinara sauce) as a breakfast side is technically CACFP-creditable but
                    # not a realistic breakfast choice. Only fall back to lunch's vegetable if the
                    # tenant has no fruit components in their library at all.
                    fruit = lunch_fruit or await pick_component(db, tenant_id, type_name_to_id, "Fruit") or lunch_vegetable
                    grain = await pick_component(
                        db, tenant_id, type_name_to_id, "Grain",
                        name_keywords=BREAKFAST_GRAIN_KEYWORDS,
                        exclude_ids={lunch_milk.id} if lunch_milk else None,
                    )

                    breakfast_parts = [
                        ("Milk", milk, False),
                        ("Grain", grain, False),
                        (("Fruit" if fruit and fruit.component_type_id == type_name_to_id.get("Fruit") else "Vegetable"), fruit, False),
                    ]
                    for label, fc, is_vegan in breakfast_parts:
                        if not fc:
                            print(f"  [{d}] {program.name} / breakfast: WARNING - no {label} component found in tenant library, skipped")
                            continue
                        key = ("breakfast", fc.id, is_vegan)
                        if key in existing_components:
                            continue
                        totals["breakfast_components"] += 1
                        print(f"  [{d}] {program.name} / breakfast: add {label} = '{fc.name}' (component_id={fc.id})")
                        if execute and target_day:
                            db.add(MenuDayComponent(
                                menu_day_id=target_day.id, component_id=fc.id,
                                meal_slot="breakfast", is_vegan=False, quantity=fc.default_portion_oz,
                                sort_order=0,
                            ))

                    if program.vegan_count and program.vegan_count > 0:
                        vegan_milk = await pick_component(db, tenant_id, type_name_to_id, "Milk", is_vegan=True)
                        vegan_grain = grain if (grain and grain.is_vegan) else await pick_component(
                            db, tenant_id, type_name_to_id, "Grain", is_vegan=True, name_keywords=BREAKFAST_GRAIN_KEYWORDS
                        )
                        vegan_fruit = fruit  # fruit/veg items are effectively vegan across the seeded library
                        for label, fc in [("Vegan Milk", vegan_milk), ("Vegan Grain", vegan_grain), ("Vegan Fruit/Veg", vegan_fruit)]:
                            if not fc:
                                print(f"  [{d}] {program.name} / breakfast (vegan): WARNING - no {label} component found, skipped")
                                continue
                            key = ("breakfast", fc.id, True)
                            if key in existing_components:
                                continue
                            totals["breakfast_components"] += 1
                            print(f"  [{d}] {program.name} / breakfast (vegan): add {label} = '{fc.name}' (component_id={fc.id})")
                            if execute and target_day:
                                db.add(MenuDayComponent(
                                    menu_day_id=target_day.id, component_id=fc.id,
                                    meal_slot="breakfast", is_vegan=True, quantity=fc.default_portion_oz,
                                    sort_order=0,
                                ))

            d += timedelta(days=1)

        if totals["no_template_day"]:
            print(f"\nNo template menu day found for: {totals['no_template_day']} - skipped for all targets on those dates.")

        print(f"\nPlanned: {totals['cloned_components']} cloned component(s), "
              f"{totals['breakfast_components']} synthesized breakfast component(s), "
              f"{totals['skipped_existing']} already present (skipped).")

        if execute:
            await db.commit()
            print("\nChanges committed. Next: regenerate invoices for each target program's September "
                  "monthly menu so these days get invoiced.")
        else:
            print("\nDry run only - nothing written. Re-run with --execute to apply.")


async def main():
    parser = argparse.ArgumentParser(description="Backfill menu days for target programs by cloning a template program's menu")
    parser.add_argument("--template-program-name", required=True)
    parser.add_argument("--target-program-names", required=True, help="Comma-separated program names")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--execute", action="store_true", help="Actually write changes (default is dry run)")
    args = parser.parse_args()

    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    targets = [n.strip() for n in args.target_program_names.split(",") if n.strip()]

    await backfill(args.template_program_name, targets, start, end, args.execute)


if __name__ == "__main__":
    asyncio.run(main())
