"""
Master Menu Publishing

Copies a master menu into each selected program's regular CateringMonthlyMenu for
that month, so production, invoices, the shopping list and the client portal keep
reading per-program menus exactly as before.

Per program:
- only the program's service days, minus its holidays
- only the meal slots the program requires; a program that takes "Snack" gets the
  master's PM Snack (or AM Snack) when the master has no plain Snack column, and
  vice versa
- master days marked OFF clear that day and (optionally) become program holidays
- days edited by hand in the program's calendar (is_customized) are left alone
  unless overwrite_customized is set
- finalized/sent menus are skipped unless include_locked is set, since clients can
  already see them in the portal
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.models.catering import (
    CateringMasterMenu,
    CateringMasterMenuDay,
    CateringMasterMenuComponent,
    CateringMonthlyMenu,
    CateringMenuDay,
    CateringProgram,
    CateringProgramHoliday,
    MenuDayComponent,
)

LOCKED_STATUSES = {"finalized", "sent"}


def _json_list(value) -> list:
    return json.loads(value) if isinstance(value, str) else (value or [])


def program_slots(program: CateringProgram) -> List[str]:
    return [mt.lower().replace(" ", "_") for mt in _json_list(program.meal_types_required)]


def slot_mapping(required_slots: List[str], master_slots: set) -> Dict[str, str]:
    """{master_slot: program_slot} for the slots this program takes."""
    mapping = {}
    for slot in required_slots:
        if slot in master_slots:
            mapping[slot] = slot
        elif slot == "snack":
            source = "pm_snack" if "pm_snack" in master_slots else ("am_snack" if "am_snack" in master_slots else None)
            if source and source not in required_slots:
                mapping[source] = "snack"
        elif slot in ("am_snack", "pm_snack") and "snack" in master_slots and "snack" not in required_slots:
            mapping["snack"] = slot
    return mapping


@dataclass
class PublishResult:
    program_id: str
    program_name: str
    menu_id: Optional[str] = None
    status: str = "published"  # published | skipped_locked | skipped_no_days
    created_menu: bool = False
    days_written: int = 0
    days_customized_kept: int = 0
    days_closed: int = 0
    holidays_added: int = 0
    notes: List[str] = field(default_factory=list)


async def load_master_menu(db: AsyncSession, master_menu_id: str, tenant_id: int) -> Optional[CateringMasterMenu]:
    result = await db.execute(
        select(CateringMasterMenu)
        .where(CateringMasterMenu.id == master_menu_id, CateringMasterMenu.tenant_id == tenant_id)
        .options(
            selectinload(CateringMasterMenu.days)
                .selectinload(CateringMasterMenuDay.components)
                .selectinload(CateringMasterMenuComponent.food_component),
        )
    )
    return result.scalar_one_or_none()


async def publish_master_menu(
    db: AsyncSession,
    master: CateringMasterMenu,
    program_ids: List[str],
    *,
    include_locked: bool = False,
    overwrite_customized: bool = False,
    closed_as_holidays: bool = True,
) -> List[PublishResult]:
    programs = (await db.execute(
        select(CateringProgram)
        .where(CateringProgram.tenant_id == master.tenant_id, CateringProgram.id.in_(program_ids))
        .options(selectinload(CateringProgram.holidays))
        .order_by(CateringProgram.name)
    )).scalars().all()

    menus = (await db.execute(
        select(CateringMonthlyMenu)
        .where(
            CateringMonthlyMenu.tenant_id == master.tenant_id,
            CateringMonthlyMenu.program_id.in_(program_ids),
            CateringMonthlyMenu.month == master.month,
            CateringMonthlyMenu.year == master.year,
            CateringMonthlyMenu.menu_type == "regular",
        )
        .options(selectinload(CateringMonthlyMenu.menu_days).selectinload(CateringMenuDay.components))
    )).scalars().all()
    menus_by_program = {m.program_id: m for m in menus}

    master_slots = {c.meal_slot for d in master.days for c in d.components}
    results = []

    for program in programs:
        res = PublishResult(program_id=program.id, program_name=program.name)
        results.append(res)

        menu = menus_by_program.get(program.id)
        if menu and menu.status in LOCKED_STATUSES and not include_locked:
            res.status, res.menu_id = "skipped_locked", menu.id
            res.notes.append(f"Menu is {menu.status} — clients can already see it.")
            continue

        service_days = set(_json_list(program.service_days))
        holiday_dates = {h.holiday_date for h in program.holidays}
        mapping = slot_mapping(program_slots(program), master_slots)
        if not mapping:
            res.status = "skipped_no_days"
            res.notes.append("None of this program's meal types are on the master menu.")
            continue

        if not menu:
            menu = CateringMonthlyMenu(
                program_id=program.id, month=master.month, year=master.year,
                menu_type="regular", status="draft", tenant_id=master.tenant_id,
            )
            menu.menu_days = []
            db.add(menu)
            res.created_menu = True
        menu.master_menu_id = master.id
        days_by_date = {d.service_date: d for d in menu.menu_days}

        to_fill = []  # (menu day, master day)
        for mday in master.days:
            d = mday.service_date
            if d.strftime("%A") not in service_days:
                continue
            existing = days_by_date.get(d)

            if mday.is_closed:
                if existing and (overwrite_customized or not existing.is_customized):
                    menu.menu_days.remove(existing)
                    res.days_closed += 1
                if closed_as_holidays and d not in holiday_dates:
                    program.holidays.append(CateringProgramHoliday(holiday_date=d, description=mday.closed_reason or "Closed"))
                    holiday_dates.add(d)
                    res.holidays_added += 1
                continue
            if d in holiday_dates:
                continue

            if existing and existing.is_customized and not overwrite_customized:
                res.days_customized_kept += 1
                continue

            day = existing
            if day is None:
                day = CateringMenuDay(service_date=d)
                day.components = []
                menu.menu_days.append(day)
                days_by_date[d] = day
            day.components.clear()
            day.is_customized = False
            if mday.notes:
                day.notes = mday.notes
            to_fill.append((day, mday))

        # Old components must be deleted before the new rows go in: the unit of work
        # inserts before it deletes, which would trip uq_menu_day_component.
        await db.flush()
        for day, mday in to_fill:
            for comp in mday.components:
                target_slot = mapping.get(comp.meal_slot)
                if not target_slot:
                    continue
                day.components.append(MenuDayComponent(
                    component_id=comp.component_id,
                    meal_slot=target_slot,
                    is_vegan=comp.is_vegan,
                    sort_order=comp.sort_order,
                ))
            res.days_written += 1

        await db.flush()
        res.menu_id = menu.id
        if res.days_written == 0 and res.days_customized_kept == 0:
            res.notes.append("No master-menu days fall on this program's service days.")

    master.status = "published"
    master.published_at = datetime.utcnow()
    await db.commit()
    return results
