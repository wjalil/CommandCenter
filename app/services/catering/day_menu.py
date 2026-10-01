"""
Day Menu Resolver

The single answer to "what is program X actually getting for meal Y on date Z?" —
the planned menu day (component-first or pre-built meal item mode) with that
day's substitutions applied. Kitchen Prep, Packaging, the driver manifest and the
Daily Delivery Invoice all read through here, so a sub made on the Production
Sheet reaches every one of them the same way.
"""
import json
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.models.catering import (
    CateringMonthlyMenu,
    CateringMenuDay,
    CateringMealItem,
    CateringMealComponent,
    CateringSubstitution,
    FoodComponent,
    MenuDayComponent,
)

SLOTS = ("breakfast", "lunch", "snack", "am_snack", "pm_snack")
SNACK_SLOTS = ("snack", "pm_snack", "am_snack")


@dataclass
class ResolvedComponent:
    name: str
    component_id: Optional[int]
    type_name: str
    qty_oz: float
    original_name: Optional[str] = None  # set when this replaced a planned item
    original_component_id: Optional[int] = None
    substitution_id: Optional[str] = None
    reason: Optional[str] = None

    @property
    def is_sub(self) -> bool:
        return self.substitution_id is not None


def required_slots(program) -> List[str]:
    meal_types = program.meal_types_required
    if isinstance(meal_types, str):
        meal_types = json.loads(meal_types)
    return [mt.lower().replace(" ", "_") for mt in (meal_types or [])]


def effective_slot_counts(program, overrides_for_program: Optional[dict]) -> tuple:
    """Per-slot (count, vegan) dicts for one program on one date — a same-day
    CateringDailyCount override when present, else the program's standing count
    (which itself falls back to legacy total_children)."""
    counts = {}
    for slot in SLOTS:
        value = getattr(program, f"{slot}_count")
        counts[slot] = value if value is not None else program.total_children
    vegan = {slot: 0 for slot in SLOTS}
    vegan["breakfast"] = program.breakfast_vegan_count or 0
    vegan["lunch"] = program.lunch_vegan_count or 0
    for slot, override in (overrides_for_program or {}).items():
        counts[slot] = override.count
        vegan[slot] = override.vegan_count
    return counts, vegan


def _component_options(rel):
    return rel.selectinload(FoodComponent.component_type)


def menu_day_load_options(prefix=None):
    """selectinload options that pull everything the resolver touches on a menu
    day (both modes, with CACFP component types). `prefix` chains them under a
    parent loader, e.g. selectinload(CateringMonthlyMenu.menu_days)."""
    def start(attr):
        return prefix.selectinload(attr) if prefix is not None else selectinload(attr)

    options = [
        _component_options(start(CateringMenuDay.components).selectinload(MenuDayComponent.food_component)),
    ]
    for slot in SLOTS:
        for suffix in ("", "_vegan"):
            attr = getattr(CateringMenuDay, f"{slot}{suffix}_item")
            options.append(_component_options(
                start(attr).selectinload(CateringMealItem.components).selectinload(CateringMealComponent.food_component)
            ))
    return options


async def load_menu_days(db: AsyncSession, program_ids: Iterable[str], service_date: date) -> Dict[str, CateringMenuDay]:
    """{program_id: menu day} for one date, in one query instead of one per program."""
    program_ids = list(program_ids)
    if not program_ids:
        return {}
    result = await db.execute(
        select(CateringMenuDay)
        .join(CateringMonthlyMenu, CateringMenuDay.monthly_menu_id == CateringMonthlyMenu.id)
        .where(
            CateringMonthlyMenu.program_id.in_(program_ids),
            CateringMonthlyMenu.month == service_date.month,
            CateringMonthlyMenu.year == service_date.year,
            CateringMonthlyMenu.menu_type == "regular",
            CateringMenuDay.service_date == service_date,
        )
        .options(selectinload(CateringMenuDay.monthly_menu), *menu_day_load_options())
    )
    return {day.monthly_menu.program_id: day for day in result.scalars().all()}


async def load_substitutions(db: AsyncSession, tenant_id: int, service_date: date) -> List[CateringSubstitution]:
    result = await db.execute(
        select(CateringSubstitution)
        .where(CateringSubstitution.tenant_id == tenant_id, CateringSubstitution.service_date == service_date)
        .options(
            selectinload(CateringSubstitution.replacement_component).selectinload(FoodComponent.component_type),
            selectinload(CateringSubstitution.original_component).selectinload(FoodComponent.component_type),
            selectinload(CateringSubstitution.program),
        )
        .order_by(CateringSubstitution.created_at)
    )
    return list(result.scalars().all())


def _type_name(food_component) -> str:
    ct = food_component.component_type if food_component else None
    return ct.name if ct else ""


def planned_slot_components(menu_day, slot: str, is_vegan: bool = False) -> List[ResolvedComponent]:
    """The menu's own items for one slot: component-first rows if the day has any
    for that slot, else the pre-built meal item's components."""
    if not menu_day:
        return []
    out, seen = [], set()
    rows = sorted(
        (c for c in menu_day.components if c.meal_slot == slot and c.is_vegan == is_vegan and c.food_component),
        key=lambda c: c.sort_order,
    )
    if rows:
        for c in rows:
            fc = c.food_component
            if fc.name in seen:
                continue
            seen.add(fc.name)
            out.append(ResolvedComponent(fc.name, fc.id, _type_name(fc), float(c.quantity or fc.default_portion_oz or 0)))
        return out

    item = getattr(menu_day, f"{slot}{'_vegan' if is_vegan else ''}_item", None)
    if item and item.components:
        for mc in item.components:
            fc = mc.food_component
            if not fc or fc.name in seen:
                continue
            seen.add(fc.name)
            out.append(ResolvedComponent(fc.name, fc.id, _type_name(fc), float(mc.portion_oz or 0)))
    return out


def program_slot_source(menu_day, slot: str, slots_required: List[str], is_vegan: bool = False) -> str:
    """Which menu slot feeds this program's slot — itself, or for a snack program
    whose menu has its snack under another snack column ("Snack" vs "PM Snack"),
    that other column."""
    if planned_slot_components(menu_day, slot, is_vegan) or slot not in SNACK_SLOTS:
        return slot
    for other in SNACK_SLOTS:
        if other != slot and other not in slots_required and planned_slot_components(menu_day, other, is_vegan):
            return other
    return slot


def _match(subs: List[CateringSubstitution], component_id, slot: str, is_vegan: bool, program_id: str):
    best, best_score = None, -1
    for sub in subs:
        if sub.original_component_id != component_id or sub.is_vegan != is_vegan:
            continue
        if sub.meal_slot is not None and sub.meal_slot != slot:
            continue
        if sub.program_id is not None and sub.program_id != program_id:
            continue
        score = (2 if sub.program_id else 0) + (1 if sub.meal_slot else 0)
        if score >= best_score:  # later rows win ties
            best, best_score = sub, score
    return best


def apply_substitutions(components: List[ResolvedComponent], slot: str, is_vegan: bool,
                        subs: List[CateringSubstitution], program_id: str) -> List[ResolvedComponent]:
    if not subs:
        return components
    out, seen = [], set()
    for comp in components:
        sub = _match(subs, comp.component_id, slot, is_vegan, program_id)
        if sub and sub.replacement_component:
            rc = sub.replacement_component
            type_name = _type_name(rc)
            if sub.portion_oz is not None:
                qty = float(sub.portion_oz)
            elif type_name == comp.type_name:
                qty = comp.qty_oz  # like-for-like swap keeps the planned serving size
            else:
                qty = float(rc.default_portion_oz or 0)
            comp = ResolvedComponent(
                rc.name, rc.id, type_name, qty,
                original_name=comp.name, original_component_id=comp.component_id,
                substitution_id=sub.id, reason=sub.reason,
            )
        if comp.name in seen:
            continue
        seen.add(comp.name)
        out.append(comp)
    return out


def resolve_slot(menu_day, slot: str, slots_required: List[str], subs: List[CateringSubstitution],
                 program_id: str, is_vegan: bool = False) -> List[ResolvedComponent]:
    """What this program is actually served for one of its slots."""
    source = program_slot_source(menu_day, slot, slots_required, is_vegan)
    planned = planned_slot_components(menu_day, source, is_vegan)
    # Subs are keyed by the program's slot; a kitchen-wide "any slot" sub matches either way.
    return apply_substitutions(planned, slot, is_vegan, subs, program_id)


def subs_in_scope(subs: List[CateringSubstitution], program_id: str) -> List[CateringSubstitution]:
    return [s for s in subs if s.program_id is None or s.program_id == program_id]
