"""
Daily Delivery Invoice (DDI)

Builds the per-program, per-day delivery invoice from what the kitchen actually
sent: the day's resolved menu (planned menu + substitutions, see day_menu) and
the day's confirmed headcounts. The result is frozen into CateringInvoiceLine
rows so the record never changes when a menu is edited later.

Format follows the NYS DOH CACFP vendor contract (CACFP-142B, "The Daily Delivery
Invoice"): vendor name, center name + address, delivery date, number of meals,
the type of each food (milk, cereal, fruit...), and a signature line for the
center staff receiving the meals. Bulk (family style) deliveries show the total
amount of each food; unitized (individual) deliveries list what each meal contains.

Lifecycle: draft (rebuilt on demand, following the kitchen) -> edited by hand
(stops following the kitchen until "Reset from kitchen") -> finalized when the
route's manifest is released (locked; reopening the manifest unlocks it).

Supplies (spoons, sporks...) ride on the same invoice as lines with meal_slot
SUPPLY_SLOT: hand-added one-offs, billed separately, never counted as meals,
and kept through every rebuild.
"""
import json
from dataclasses import replace
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.models.catering import (
    CACFPAgeGroup,
    CACFPComponentType,
    CateringInvoice,
    CateringInvoiceLine,
    CateringProgram,
    FoodComponent,
    ProductionDailyLog,
)
from app.crud.catering import cacfp_rules
from app.crud.catering import daily_count as daily_count_crud
from app.crud.catering.program import increment_invoice_number
from app.services.catering import day_menu

# Shown on every DDI. Single place to change it.
VENDOR = {
    "name": "Chai and Biscuit LLC",
    "address": "6014 Fresh Pond Rd, Maspeth, NY 11378",
    "phone": "347-738-5048",
}

LOCKED_STATUSES = {"finalized", "sent"}
SUPPLY_SLOT = "supplies"

# Chronological, as the meals are served.
DDI_SLOT_ORDER = ("breakfast", "am_snack", "lunch", "snack", "pm_snack")
SLOT_NAMES = {
    "breakfast": "Breakfast",
    "am_snack": "AM Snack",
    "lunch": "Lunch",
    "snack": "Snack",
    "pm_snack": "PM Snack",
}


def is_locked(invoice: Optional[CateringInvoice]) -> bool:
    return bool(invoice) and invoice.status in LOCKED_STATUSES


def follows_kitchen(invoice: Optional[CateringInvoice]) -> bool:
    """A draft nobody has edited by hand — rebuilt from the kitchen on every load."""
    return bool(invoice) and not is_locked(invoice) and invoice.edited_at is None


async def produce_names(db: AsyncSession, tenant_id: int) -> List[str]:
    """Food components whose CACFP type contains "fruit" — what the Packaging
    screen packs via the Produce card instead of as meal lines."""
    result = await db.execute(
        select(FoodComponent.name)
        .join(FoodComponent.component_type)
        .where(
            FoodComponent.tenant_id == tenant_id,
            CACFPComponentType.name.ilike("%fruit%"),
        )
        .order_by(FoodComponent.name)
    )
    return [row[0] for row in result.all()]


async def default_milk_type(db: AsyncSession, program: CateringProgram) -> str:
    """CACFP: unflavored whole milk at age 1; low-fat or fat-free from age 2 up."""
    if program.milk_type:
        return program.milk_type
    age_group = await db.get(CACFPAgeGroup, program.age_group_id)
    if age_group and age_group.age_max_months is not None and age_group.age_max_months <= 24:
        return "Whole Milk"
    return "1% Low-Fat Milk"


async def _produce_sent(db: AsyncSession, tenant_id: int, program_id: str, service_date: date) -> List[str]:
    """Fruit picked on the Packaging screen's Produce card for this program today —
    names the 'type of fruit' the DDI requires instead of a generic line."""
    result = await db.execute(
        select(ProductionDailyLog).where(
            ProductionDailyLog.tenant_id == tenant_id,
            ProductionDailyLog.program_id == program_id,
            ProductionDailyLog.service_date == service_date,
            ProductionDailyLog.check_type == "produce",
        )
    )
    names = []
    for log in result.scalars().all():
        try:
            items = json.loads(log.reference_key) if log.reference_key else []
        except (ValueError, TypeError):
            items = [log.reference_key]
        for item in items if isinstance(items, list) else [items]:
            if item and item not in names:
                names.append(item)
    return names


def _with_produce(items: list, produce: List[str], produce_set: set) -> list:
    """The Produce card is what actually went in the bag: a meal's fruit becomes
    the picked fruit (one line, at the menu's portion), and the menu's fruit is
    kept as substituted_for so the swap is documented on the DDI."""
    if not produce:
        return items
    picked, out, placed = ", ".join(produce), [], False
    for comp in items:
        if comp.name not in produce_set:
            out.append(comp)
            continue
        if placed:
            continue
        placed = True
        planned = comp.original_name or comp.name
        swapped = planned not in produce
        out.append(replace(
            comp, name=picked, original_name=planned if swapped else None,
            reason=comp.reason if (swapped and comp.original_name) else None,
        ))
    return out


async def build_lines(db: AsyncSession, program: CateringProgram, menu_day, counts: dict, vegan: dict,
                      subs: list, produce: List[str], produce_set: Optional[set] = None) -> tuple:
    """(lines, slot_counts): the line dicts for every meal this program receives,
    and {slot: (regular_count, vegan_count)} for the meals actually delivered.
    Fruit picked on the Produce card replaces the menu's fruit at every meal."""
    slots_required = day_menu.required_slots(program)
    milk = await cacfp_rules.get_milk_portions(db, program.age_group_id) if program.cacfp_eligible else {}
    fruit = await cacfp_rules.get_fruit_portions(db, program.age_group_id) if program.cacfp_eligible else {}
    milk_name = await default_milk_type(db, program) if milk else None

    lines, slot_counts, order = [], {}, 0
    for slot in DDI_SLOT_ORDER:
        if slot not in slots_required:
            continue
        regular_items = day_menu.resolve_slot(menu_day, slot, slots_required, subs, program.id, is_vegan=False)
        vegan_items = day_menu.resolve_slot(menu_day, slot, slots_required, subs, program.id, is_vegan=True)
        if not regular_items and not vegan_items:
            continue
        total = counts.get(slot) or 0
        # Vegan kids only come off the regular count when a vegan alternative exists
        # that day — otherwise they eat (and are invoiced for) the regular meal.
        vegan_n = min(vegan.get(slot) or 0, total) if vegan_items else 0
        regular_n = total - vegan_n
        slot_counts[slot] = (regular_n if regular_items else 0, vegan_n)

        for is_vegan, items, n in ((False, regular_items, regular_n), (True, vegan_items, vegan_n)):
            if not items or n <= 0:
                continue
            items = _with_produce(items, produce, produce_set or set())
            for comp in items:
                order += 1
                lines.append(dict(
                    meal_slot=slot, is_vegan=is_vegan, meal_count=n, component_type=comp.type_name or None,
                    item_name=comp.name, portion_qty=round(comp.qty_oz, 2), portion_unit="oz",
                    substituted_for=comp.original_name, substitution_reason=comp.reason, is_auto=False,
                    sort_order=order,
                ))
            types = {c.type_name for c in items}
            if milk.get(slot) and "Milk" not in types:
                order += 1
                lines.append(dict(
                    meal_slot=slot, is_vegan=is_vegan, meal_count=n, component_type="Milk", item_name=milk_name,
                    portion_qty=float(milk[slot]), portion_unit="fl oz", is_auto=True, sort_order=order,
                ))
            if slot == "lunch" and fruit.get("lunch") and "Fruit" not in types:
                order += 1
                lines.append(dict(
                    meal_slot=slot, is_vegan=is_vegan, meal_count=n, component_type="Fruit",
                    item_name=", ".join(produce) if produce else "Seasonal Fruit",
                    portion_qty=float(fruit["lunch"]), portion_unit="cup", is_auto=True, sort_order=order,
                ))
    return lines, slot_counts


async def get_invoice_for(db: AsyncSession, program_id: str, service_date: date) -> Optional[CateringInvoice]:
    result = await db.execute(
        select(CateringInvoice)
        .where(CateringInvoice.program_id == program_id, CateringInvoice.service_date == service_date)
        .options(selectinload(CateringInvoice.lines), selectinload(CateringInvoice.program))
        .order_by(CateringInvoice.created_at)
    )
    return result.scalars().first()


def _apply_counts(invoice: CateringInvoice, program: CateringProgram, slot_counts: dict):
    for slot in day_menu.SLOTS:
        regular_n, vegan_n = slot_counts.get(slot, (None, 0))
        setattr(invoice, f"{slot}_count", regular_n if slot in slot_counts else None)
        setattr(invoice, f"{slot}_vegan_count", vegan_n or 0)
    invoice.regular_meal_count = program.total_children - (program.vegan_count or 0)
    invoice.vegan_meal_count = program.vegan_count or 0


def _snapshot(invoice: CateringInvoice, program: CateringProgram):
    invoice.site_name = program.name
    invoice.site_address = program.address
    invoice.client_name = program.client_name
    invoice.service_style = program.meal_service_style
    invoice.is_cacfp = bool(program.cacfp_eligible)


async def build_invoice(db: AsyncSession, program: CateringProgram, service_date: date, *,
                        menu_day=None, subs=None, overrides=None, produce_set=None,
                        commit: bool = True) -> Optional[CateringInvoice]:
    """Create or rebuild the DDI for one program on one date. A locked or
    hand-edited invoice is returned untouched. Supply lines survive a rebuild.
    Returns None when the program has nothing on the menu."""
    tenant_id = program.tenant_id
    invoice = await get_invoice_for(db, program.id, service_date)
    if invoice is not None and not follows_kitchen(invoice):
        return invoice

    if menu_day is None:
        menu_day = (await day_menu.load_menu_days(db, [program.id], service_date)).get(program.id)
    if menu_day is None:
        return invoice
    if subs is None:
        subs = await day_menu.load_substitutions(db, tenant_id, service_date)
    if overrides is None:
        overrides = await daily_count_crud.get_counts_for_program_date(db, program.id, service_date)

    if produce_set is None:
        produce_set = set(await produce_names(db, tenant_id))

    counts, vegan = day_menu.effective_slot_counts(program, overrides)
    produce = await _produce_sent(db, tenant_id, program.id, service_date)
    lines, slot_counts = await build_lines(db, program, menu_day, counts, vegan, subs, produce, produce_set)
    if not lines:
        return invoice

    if invoice is None:
        number = await increment_invoice_number(db, program.id)
        invoice = CateringInvoice(
            invoice_number=number, program_id=program.id, service_date=service_date,
            regular_meal_count=0, status="draft", tenant_id=tenant_id, lines=[],
        )
        invoice.program = program
        db.add(invoice)
    invoice.menu_day_id = menu_day.id
    invoice.monthly_menu_id = menu_day.monthly_menu_id
    _apply_counts(invoice, program, slot_counts)
    _snapshot(invoice, program)
    invoice.lines = [CateringInvoiceLine(**line) for line in lines] + supply_lines(invoice)
    invoice.updated_at = datetime.utcnow()
    if commit:
        await db.commit()
    return invoice


async def refresh(db: AsyncSession, invoice: CateringInvoice) -> CateringInvoice:
    """The invoice as it should read right now: a draft that follows the kitchen
    is rebuilt (so a Produce card or count change shows up), anything else is
    only given lines if it predates them."""
    if follows_kitchen(invoice):
        program = invoice.program or await db.get(CateringProgram, invoice.program_id)
        rebuilt = await build_invoice(db, program, invoice.service_date)
        if rebuilt is not None:
            return rebuilt
    return await ensure_lines(db, invoice)


async def reset_from_kitchen(db: AsyncSession, invoice: CateringInvoice) -> CateringInvoice:
    """Throw away hand edits to the meals and rebuild from the kitchen. Supplies stay."""
    if is_locked(invoice):
        return invoice
    invoice.edited_at = None
    invoice.edited_by_user_id = None
    await db.commit()
    return await refresh(db, invoice)


def _meal_signature(lines) -> list:
    return sorted(
        (l.meal_slot, bool(l.is_vegan), int(l.meal_count or 0), l.component_type or "", l.item_name,
         round(float(l.portion_qty), 2) if l.portion_qty is not None else None, l.portion_unit or "",
         l.substituted_for or "", l.substitution_reason or "")
        for l in lines if l.meal_slot != SUPPLY_SLOT
    )


def _number(value, minimum=0.0) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= minimum else None


class InvoiceEditError(ValueError):
    pass


def apply_edits(invoice: CateringInvoice, meals: list, supplies: list, user_id: Optional[str] = None) -> bool:
    """Replace a draft's lines with the edited ones from the invoice editor.

    meals:    [{slot, is_vegan, meal_count, lines: [{component_type, item_name,
               portion_qty, portion_unit, substituted_for, substitution_reason, is_auto}]}]
    supplies: [{item_name, qty}]
    The headcounts typed here are what was served — they stay on this invoice
    (the monthly audit reads them), they don't change the kitchen's numbers.
    Returns True when the meals changed (the draft then stops following the kitchen)."""
    if is_locked(invoice):
        raise InvoiceEditError("This invoice is locked — its route was released. Reopen the route to edit it.")

    before = _meal_signature(invoice.lines)
    new_lines, slot_counts, seen, order = [], {}, set(), 0
    for meal in meals or []:
        slot = meal.get("slot")
        if slot not in DDI_SLOT_ORDER:
            raise InvoiceEditError(f"Unknown meal: {slot}")
        is_vegan = bool(meal.get("is_vegan"))
        if (slot, is_vegan) in seen:
            raise InvoiceEditError(f"{SLOT_NAMES[slot]} is listed twice.")
        seen.add((slot, is_vegan))
        count = _number(meal.get("meal_count"))
        if count is None or count != int(count):
            raise InvoiceEditError(f"{SLOT_NAMES[slot]}: meal count must be a whole number.")
        count = int(count)
        meal_lines = [l for l in meal.get("lines") or [] if str(l.get("item_name") or "").strip()]
        if not meal_lines or count == 0:
            continue  # an emptied meal block = that meal wasn't delivered
        regular_n, vegan_n = slot_counts.get(slot, (0, 0))
        slot_counts[slot] = (regular_n, count) if is_vegan else (count, vegan_n)
        for line in meal_lines:
            order += 1
            qty = line.get("portion_qty")
            portion = _number(qty) if qty not in (None, "") else None
            if qty not in (None, "") and portion is None:
                raise InvoiceEditError(f"{SLOT_NAMES[slot]} / {line['item_name']}: portion must be a number.")
            new_lines.append(CateringInvoiceLine(
                meal_slot=slot, is_vegan=is_vegan, meal_count=count,
                component_type=(str(line.get("component_type") or "").strip() or None),
                item_name=str(line["item_name"]).strip()[:200],
                portion_qty=round(portion, 2) if portion is not None else None,
                portion_unit=(str(line.get("portion_unit") or "").strip()[:20] or None),
                substituted_for=(str(line.get("substituted_for") or "").strip()[:200] or None),
                substitution_reason=(str(line.get("substitution_reason") or "").strip() or None),
                is_auto=bool(line.get("is_auto")), sort_order=order,
            ))

    for i, supply in enumerate(supplies or []):
        name = str(supply.get("item_name") or "").strip()
        if not name:
            continue
        qty = _number(supply.get("qty"), minimum=1)
        if qty is None or qty != int(qty):
            raise InvoiceEditError(f"Supplies / {name}: quantity must be a whole number of at least 1.")
        new_lines.append(CateringInvoiceLine(
            meal_slot=SUPPLY_SLOT, is_vegan=False, meal_count=0, item_name=name[:200],
            portion_qty=int(qty), portion_unit="ea", sort_order=10000 + i,
        ))

    changed = _meal_signature(new_lines) != before
    invoice.lines = new_lines
    if changed:
        for slot in day_menu.SLOTS:
            regular_n, vegan_n = slot_counts.get(slot, (None, 0))
            setattr(invoice, f"{slot}_count", regular_n if slot in slot_counts else None)
            setattr(invoice, f"{slot}_vegan_count", vegan_n or 0)
        invoice.edited_at = datetime.utcnow()
        invoice.edited_by_user_id = user_id
    invoice.updated_at = datetime.utcnow()
    return changed


async def ensure_lines(db: AsyncSession, invoice: CateringInvoice) -> CateringInvoice:
    """Invoices made before lines existed: a draft is simply rebuilt; a locked one
    gets lines built from its own stored counts (not today's), then frozen."""
    program = invoice.program or await db.get(CateringProgram, invoice.program_id)
    if meal_lines(invoice) or invoice.edited_at:
        if not invoice.site_name:
            _snapshot(invoice, program)
            await db.commit()
        return invoice
    if not is_locked(invoice):
        rebuilt = await build_invoice(db, program, invoice.service_date)
        return rebuilt or invoice

    menu_day = (await day_menu.load_menu_days(db, [program.id], invoice.service_date)).get(program.id)
    if not menu_day:
        return invoice
    counts, vegan = {}, {}
    for slot in day_menu.SLOTS:
        regular_n = getattr(invoice, f"{slot}_count") or 0
        vegan_n = getattr(invoice, f"{slot}_vegan_count") or 0
        counts[slot], vegan[slot] = regular_n + vegan_n, vegan_n
    lines, _ = await build_lines(db, program, menu_day, counts, vegan, [], [])
    invoice.lines = [CateringInvoiceLine(**line) for line in lines] + supply_lines(invoice)
    if not invoice.site_name:
        _snapshot(invoice, program)
    await db.commit()
    return invoice


async def build_for_programs(db: AsyncSession, tenant_id: int, programs: Iterable[CateringProgram],
                             service_date: date) -> Dict[str, Optional[CateringInvoice]]:
    """Build (or leave locked) the DDI for each program, sharing one menu/sub/count load."""
    programs = list(programs)
    menu_days = await day_menu.load_menu_days(db, [p.id for p in programs], service_date)
    subs = await day_menu.load_substitutions(db, tenant_id, service_date)
    all_overrides = await daily_count_crud.get_counts_for_date(db, tenant_id, service_date)
    produce_set = set(await produce_names(db, tenant_id))
    out = {}
    for program in programs:
        out[program.id] = await build_invoice(
            db, program, service_date, menu_day=menu_days.get(program.id), subs=subs,
            overrides=all_overrides.get(program.id, {}), produce_set=produce_set, commit=False,
        )
    await db.commit()
    return out


async def finalize_for_programs(db: AsyncSession, tenant_id: int, programs: Iterable[CateringProgram],
                                service_date: date) -> int:
    """Release-time lock: rebuild each draft from the final numbers, then freeze it."""
    built = await build_for_programs(db, tenant_id, programs, service_date)
    now, locked = datetime.utcnow(), 0
    for invoice in built.values():
        if invoice is not None and invoice.status == "draft":
            invoice.status = "finalized"
            invoice.finalized_at = now
            locked += 1
    await db.commit()
    return locked


async def reopen_for_programs(db: AsyncSession, program_ids: Iterable[str], service_date: date) -> int:
    """Manifest pulled back to draft: its finalized invoices go back to draft too
    (an invoice already marked 'sent' to the client stays locked)."""
    program_ids = list(program_ids)
    if not program_ids:
        return 0
    result = await db.execute(
        select(CateringInvoice).where(
            CateringInvoice.program_id.in_(program_ids),
            CateringInvoice.service_date == service_date,
            CateringInvoice.status == "finalized",
        )
    )
    reopened = 0
    for invoice in result.scalars().all():
        invoice.status = "draft"
        invoice.finalized_at = None
        reopened += 1
    await db.commit()
    return reopened


async def locked_program_ids(db: AsyncSession, program_ids: Iterable[str], service_date: date) -> set:
    program_ids = list(program_ids)
    if not program_ids:
        return set()
    result = await db.execute(
        select(CateringInvoice.program_id).where(
            CateringInvoice.program_id.in_(program_ids),
            CateringInvoice.service_date == service_date,
            CateringInvoice.status.in_(LOCKED_STATUSES),
        )
    )
    return {row[0] for row in result.all()}


# ---------------- presentation helpers (used by the DDI templates) ----------------

def meal_lines(invoice: CateringInvoice) -> list:
    return [l for l in invoice.lines if l.meal_slot != SUPPLY_SLOT]


def supply_lines(invoice: Optional[CateringInvoice]) -> list:
    if invoice is None or "lines" not in invoice.__dict__:
        return []  # brand-new invoice — nothing loaded, nothing to keep
    return sorted((l for l in invoice.lines if l.meal_slot == SUPPLY_SLOT), key=lambda l: l.sort_order)


def invoice_supplies(invoice: CateringInvoice) -> List[dict]:
    return [{"item_name": l.item_name, "qty": int(l.portion_qty or 0)} for l in supply_lines(invoice)]


def supply_label(item: dict) -> str:
    """The manifest line for a supply, e.g. "Sporks × 30"."""
    return f"{item['item_name']} \u00d7 {item['qty']}"

def _num(value) -> str:
    value = float(value or 0)
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


_FRACTIONS = {0.125: "1/8", 0.25: "1/4", 0.333: "1/3", 0.375: "3/8", 0.5: "1/2", 0.667: "2/3", 0.75: "3/4"}


def _cups(value: float) -> str:
    whole, frac = int(value), round(value - int(value), 3)
    frac_text = next((t for f, t in _FRACTIONS.items() if abs(frac - f) < 0.01), None)
    if frac == 0:
        return str(whole)
    if frac_text:
        return f"{whole} {frac_text}" if whole else frac_text
    return _num(value)


def portion_text(line) -> str:
    qty, unit = line.portion_qty, line.portion_unit or "oz"
    if qty is None:
        return ""
    if unit == "cup":
        return f"{_cups(float(qty))} cup"
    return f"{_num(qty)} {unit}"


def total_text(line) -> str:
    """Total amount delivered, in a unit a receiving teacher can check."""
    if line.portion_qty is None:
        return f"{line.meal_count} servings"
    total = float(line.portion_qty) * line.meal_count
    unit = line.portion_unit or "oz"
    if unit == "oz":
        return f"{_num(total / 16)} lb" if total >= 16 else f"{_num(total)} oz"
    if unit == "fl oz":
        return f"{_num(total / 128)} gal" if total >= 128 else f"{_num(total)} fl oz"
    if unit == "cup":
        return f"{_num(total / 4)} qt" if total >= 8 else f"{_cups(total)} cups"
    return f"{_num(total)} {unit}"


def invoice_meals(invoice: CateringInvoice) -> List[dict]:
    """Lines grouped into the meal blocks printed on the DDI, in serving order."""
    groups: Dict[tuple, dict] = {}
    for line in sorted(meal_lines(invoice), key=lambda l: l.sort_order):
        key = (line.meal_slot, line.is_vegan)
        group = groups.setdefault(key, {
            "slot": line.meal_slot,
            "label": SLOT_NAMES.get(line.meal_slot, line.meal_slot.replace("_", " ").title()) + (" (Vegan)" if line.is_vegan else ""),
            "is_vegan": line.is_vegan,
            "meal_count": line.meal_count,
            "lines": [],
        })
        group["lines"].append({
            "component_type": line.component_type or "",
            "item_name": line.item_name,
            "portion": portion_text(line),
            "total": total_text(line),
            "servings": line.meal_count,
            "substituted_for": line.substituted_for,
            "reason": line.substitution_reason,
            # raw values for the invoice editor
            "portion_qty": float(line.portion_qty) if line.portion_qty is not None else None,
            "portion_unit": line.portion_unit or "",
            "is_auto": line.is_auto,
        })
    order = {slot: i for i, slot in enumerate(DDI_SLOT_ORDER)}
    return sorted(groups.values(), key=lambda g: (order.get(g["slot"], 99), g["is_vegan"]))


def total_meals(invoice: CateringInvoice) -> int:
    return sum(g["meal_count"] for g in invoice_meals(invoice))
