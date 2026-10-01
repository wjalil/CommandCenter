from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.catering import CateringInvoice
from app.schemas.catering import CateringInvoiceCreate, CateringInvoiceUpdate
from .program import increment_invoice_number
import uuid
from datetime import datetime


async def create_invoice(db: AsyncSession, invoice: CateringInvoiceCreate):
    """Create a new catering invoice"""
    # Generate invoice number
    invoice_number = await increment_invoice_number(db, invoice.program_id)

    new_invoice = CateringInvoice(
        id=str(uuid.uuid4()),
        invoice_number=invoice_number,
        program_id=invoice.program_id,
        monthly_menu_id=invoice.monthly_menu_id,
        menu_day_id=invoice.menu_day_id,
        service_date=invoice.service_date,
        regular_meal_count=invoice.regular_meal_count,
        vegan_meal_count=invoice.vegan_meal_count,
        # Per-meal counts
        breakfast_count=invoice.breakfast_count,
        breakfast_vegan_count=invoice.breakfast_vegan_count,
        lunch_count=invoice.lunch_count,
        lunch_vegan_count=invoice.lunch_vegan_count,
        snack_count=invoice.snack_count,
        snack_vegan_count=invoice.snack_vegan_count,
        am_snack_count=invoice.am_snack_count,
        am_snack_vegan_count=invoice.am_snack_vegan_count,
        pm_snack_count=invoice.pm_snack_count,
        pm_snack_vegan_count=invoice.pm_snack_vegan_count,
        status="draft",
        tenant_id=invoice.tenant_id
    )
    db.add(new_invoice)
    await db.commit()
    await db.refresh(new_invoice)
    return new_invoice


async def get_invoices(db: AsyncSession, tenant_id: int, program_id: str = None):
    """Get all invoices for a tenant"""
    query = select(CateringInvoice).where(CateringInvoice.tenant_id == tenant_id)

    if program_id:
        query = query.where(CateringInvoice.program_id == program_id)

    query = query.options(
        selectinload(CateringInvoice.program)
    ).order_by(CateringInvoice.service_date.desc())

    result = await db.execute(query)
    return result.scalars().all()


async def get_invoice(db: AsyncSession, invoice_id: str, tenant_id: int):
    """Get a specific invoice"""
    result = await db.execute(
        select(CateringInvoice)
        .where(CateringInvoice.id == invoice_id, CateringInvoice.tenant_id == tenant_id)
        .options(
            selectinload(CateringInvoice.program),
            selectinload(CateringInvoice.monthly_menu),
            selectinload(CateringInvoice.menu_day),
            selectinload(CateringInvoice.lines),
        )
    )
    return result.scalar_one_or_none()


async def update_invoice(db: AsyncSession, invoice_id: str, tenant_id: int, updates: CateringInvoiceUpdate):
    """Update an invoice"""
    invoice = await get_invoice(db, invoice_id, tenant_id)
    if not invoice:
        return None

    update_data = updates.dict(exclude_unset=True)

    for key, value in update_data.items():
        setattr(invoice, key, value)

    # Set sent_at timestamp when status changes to sent
    if updates.status == "sent" and not invoice.sent_at:
        invoice.sent_at = datetime.utcnow()

    await db.commit()
    await db.refresh(invoice)
    return invoice


async def generate_invoice_from_menu_day(db: AsyncSession, menu_day_id: str, tenant_id: int):
    """Generate (or rebuild, while still a draft) the Daily Delivery Invoice for a
    menu day's program and date. All the content rules live in
    services.catering.ddi so every entry point builds the same frozen record."""
    from app.models.catering import CateringMenuDay, CateringMonthlyMenu
    from app.services.catering import ddi

    result = await db.execute(
        select(CateringMenuDay)
        .where(CateringMenuDay.id == menu_day_id)
        .options(selectinload(CateringMenuDay.monthly_menu).selectinload(CateringMonthlyMenu.program))
    )
    menu_day = result.scalar_one_or_none()
    if not menu_day or menu_day.monthly_menu.tenant_id != tenant_id:
        return None
    return await ddi.build_invoice(db, menu_day.monthly_menu.program, menu_day.service_date)


async def generate_bulk_invoices_for_month(db: AsyncSession, monthly_menu_id: str, tenant_id: int):
    """Generate invoices for all menu days in a monthly menu, skipping program holidays"""
    from .monthly_menu import get_monthly_menu
    from app.models.catering import CateringProgramHoliday

    monthly_menu = await get_monthly_menu(db, monthly_menu_id, tenant_id)
    if not monthly_menu:
        return []

    # Load program holidays to skip closed days
    holidays_result = await db.execute(
        select(CateringProgramHoliday).where(
            CateringProgramHoliday.program_id == monthly_menu.program_id
        )
    )
    holiday_dates = {h.holiday_date for h in holidays_result.scalars().all()}

    generated_invoices = []
    for menu_day in monthly_menu.menu_days:
        # Skip program-closed days
        if menu_day.service_date in holiday_dates:
            continue

        # Check both pre-built meal items and component-first mode
        has_meal_items = (
            menu_day.breakfast_item_id or menu_day.lunch_item_id or menu_day.snack_item_id
            or menu_day.am_snack_item_id or menu_day.pm_snack_item_id
        )
        has_components = hasattr(menu_day, 'components') and menu_day.components and len(menu_day.components) > 0
        if has_meal_items or has_components:
            invoice = await generate_invoice_from_menu_day(db, menu_day.id, tenant_id)
            if invoice:
                generated_invoices.append(invoice)

    return generated_invoices


async def delete_invoice(db: AsyncSession, invoice_id: str, tenant_id: int):
    """Delete a draft invoice. Finalized/sent invoices are delivery records CACFP
    requires us to keep, so they can't be deleted (returns the invoice unchanged)."""
    from app.services.catering.ddi import is_locked
    invoice = await get_invoice(db, invoice_id, tenant_id)
    if invoice and not is_locked(invoice):
        await db.delete(invoice)
        await db.commit()
    return invoice
