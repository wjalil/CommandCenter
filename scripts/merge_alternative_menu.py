"""
Merge an "alternative" (vegan) monthly menu into the matching "regular" monthly
menu for the same program/month, so that a single invoice generation pass picks
up BOTH the regular and vegan counts for each day.

Why this is needed:
  The invoice generator (app/crud/catering/invoice.py: generate_invoice_from_menu_day)
  only looks at ONE CateringMenuDay row per service_date. If the vegan meals for
  a month were built as a separate "alternative" CateringMonthlyMenu (its own set
  of CateringMenuDay rows, same dates), the regular invoice run never sees them -
  you get either all-regular counts or all-vegan counts, never both in one invoice.
  The schema already supports both on ONE day (lunch_item_id + lunch_vegan_item_id,
  or MenuDayComponent.is_vegan), so the fix is to copy each alt day's meal
  data into the vegan slot(s) of the matching regular day, once.

Safe by default: runs as a DRY RUN and only prints what it would change.
Pass --execute to actually write the changes.

Usage:
    python scripts/merge_alternative_menu.py --program-id <ID> --month 9 --year 2026
    python scripts/merge_alternative_menu.py --program-id <ID> --month 9 --year 2026 --execute

After running with --execute, regenerate invoices for the regular menu (the
"Generate Invoices" button on that monthly menu, or the bulk-generate route) so
the corrected regular+vegan counts populate/update the invoices.
"""

import asyncio
import sys
import os
import argparse

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.db import async_session
from app.models.catering import CateringMonthlyMenu, CateringMenuDay, MenuDayComponent, CateringProgram

MEAL_SLOTS = ["breakfast", "lunch", "snack", "am_snack", "pm_snack"]


async def load_menu(db, program_id: str, month: int, year: int, menu_type: str):
    result = await db.execute(
        select(CateringMonthlyMenu)
        .where(
            CateringMonthlyMenu.program_id == program_id,
            CateringMonthlyMenu.month == month,
            CateringMonthlyMenu.year == year,
            CateringMonthlyMenu.menu_type == menu_type,
        )
        .options(
            selectinload(CateringMonthlyMenu.menu_days).selectinload(CateringMenuDay.components),
        )
    )
    return result.scalar_one_or_none()


async def merge(program_id: str, month: int, year: int, execute: bool):
    async with async_session() as db:
        program = await db.get(CateringProgram, program_id)
        if not program:
            print(f"No program found with id {program_id}")
            return

        regular_menu = await load_menu(db, program_id, month, year, "regular")
        alt_menu = await load_menu(db, program_id, month, year, "alternative")

        if not regular_menu:
            print(f"No 'regular' monthly menu found for {program.name} {month}/{year}")
            return
        if not alt_menu:
            print(f"No 'alternative' monthly menu found for {program.name} {month}/{year}")
            return

        print(f"Program: {program.name}")
        print(f"Regular menu: {regular_menu.id}  ({len(regular_menu.menu_days)} days)")
        print(f"Alternative menu: {alt_menu.id}  ({len(alt_menu.menu_days)} days)")
        print(f"Mode: {'EXECUTE (writing changes)' if execute else 'DRY RUN (no changes written)'}\n")

        regular_by_date = {d.service_date: d for d in regular_menu.menu_days}

        unmatched_dates = []
        planned_component_inserts = 0
        planned_item_id_sets = 0
        skipped_conflicts = 0

        for alt_day in sorted(alt_menu.menu_days, key=lambda d: d.service_date):
            reg_day = regular_by_date.get(alt_day.service_date)
            if not reg_day:
                unmatched_dates.append(alt_day.service_date)
                continue

            existing_vegan_components = {
                (c.meal_slot, c.component_id) for c in reg_day.components if c.is_vegan
            }

            for slot in MEAL_SLOTS:
                # Component-first mode: copy alt day's components for this slot
                # into the regular day as vegan components for that slot.
                alt_slot_components = [c for c in alt_day.components if c.meal_slot == slot]
                for comp in alt_slot_components:
                    if (slot, comp.component_id) in existing_vegan_components:
                        continue  # already has a vegan component here, don't duplicate/overwrite
                    planned_component_inserts += 1
                    print(f"  [{alt_day.service_date}] {slot}: add vegan component_id={comp.component_id} "
                          f"(qty={comp.quantity}, sort_order={comp.sort_order})")
                    if execute:
                        db.add(MenuDayComponent(
                            menu_day_id=reg_day.id,
                            component_id=comp.component_id,
                            meal_slot=slot,
                            is_vegan=True,
                            quantity=comp.quantity,
                            sort_order=comp.sort_order,
                            notes=comp.notes,
                        ))

                # Pre-built meal-item mode: copy alt day's <slot>_item_id into
                # regular day's <slot>_vegan_item_id, only if that slot is empty.
                alt_item_id = getattr(alt_day, f"{slot}_item_id")
                reg_vegan_item_id = getattr(reg_day, f"{slot}_vegan_item_id")
                if alt_item_id and not reg_vegan_item_id:
                    planned_item_id_sets += 1
                    print(f"  [{alt_day.service_date}] {slot}: set {slot}_vegan_item_id = {alt_item_id}")
                    if execute:
                        setattr(reg_day, f"{slot}_vegan_item_id", alt_item_id)
                elif alt_item_id and reg_vegan_item_id and reg_vegan_item_id != alt_item_id:
                    skipped_conflicts += 1
                    print(f"  [{alt_day.service_date}] {slot}: SKIPPED - regular day already has a "
                          f"different {slot}_vegan_item_id ({reg_vegan_item_id}); left untouched")

        if unmatched_dates:
            print(f"\n{len(unmatched_dates)} alternative-menu date(s) have no matching regular-menu day "
                  f"(left untouched, review manually): {unmatched_dates}")

        print(f"\nPlanned: {planned_component_inserts} vegan component row(s) to add, "
              f"{planned_item_id_sets} vegan meal-item link(s) to set, "
              f"{skipped_conflicts} conflict(s) skipped.")

        if execute:
            await db.commit()
            print("\nChanges committed. Next: regenerate invoices for the regular monthly menu "
                  "so the merged regular+vegan counts populate the invoice records.")
        else:
            print("\nDry run only - nothing written. Re-run with --execute to apply.")


async def main():
    parser = argparse.ArgumentParser(description="Merge an alternative (vegan) monthly menu into the regular one")
    parser.add_argument("--program-id", required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--execute", action="store_true", help="Actually write changes (default is dry run)")
    args = parser.parse_args()

    await merge(args.program_id, args.month, args.year, args.execute)


if __name__ == "__main__":
    asyncio.run(main())
