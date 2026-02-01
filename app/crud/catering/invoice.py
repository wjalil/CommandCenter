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
            selectinload(CateringInvoice.menu_day)
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
    """Generate an invoice from a specific menu day"""
    from .monthly_menu import get_monthly_menu
    from app.models.catering import CateringMenuDay

    # Get the menu day with all relationships
    result = await db.execute(
        select(CateringMenuDay)
        .where(CateringMenuDay.id == menu_day_id)
        .options(
            selectinload(CateringMenuDay.monthly_menu).selectinload(from_='monthly_menu').selectinload('program'),
            selectinload(CateringMenuDay.breakfast_item).selectinload('components').selectinload('food_component'),
            selectinload(CateringMenuDay.breakfast_vegan_item).selectinload('components').selectinload('food_component'),
            selectinload(CateringMenuDay.lunch_item).selectinload('components').selectinload('food_component'),
            selectinload(CateringMenuDay.lunch_vegan_item).selectinload('components').selectinload('food_component'),
            selectinload(CateringMenuDay.snack_item).selectinload('components').selectinload('food_component'),
            selectinload(CateringMenuDay.snack_vegan_item).selectinload('components').selectinload('food_component'),
        )
    )
    menu_day = result.scalar_one_or_none()

    if not menu_day:
        return None

    monthly_menu = menu_day.monthly_menu
    program = monthly_menu.program

    # Check if invoice already exists for this day
    existing = await db.execute(
        select(CateringInvoice).where(
            CateringInvoice.menu_day_id == menu_day_id,
            CateringInvoice.tenant_id == tenant_id
        )
    )
    if existing.scalar_one_or_none():
        return None  # Invoice already exists

    # Get per-meal counts (fall back to legacy total_children if not set)
    breakfast_count = program.breakfast_count if program.breakfast_count is not None else program.total_children
    breakfast_vegan = program.breakfast_vegan_count or 0
    lunch_count = program.lunch_count if program.lunch_count is not None else program.total_children
    lunch_vegan = program.lunch_vegan_count or 0
    snack_count = program.snack_count if program.snack_count is not None else program.total_children

    # Create invoice with per-meal counts
    invoice_data = CateringInvoiceCreate(
        program_id=program.id,
        monthly_menu_id=monthly_menu.id,
        menu_day_id=menu_day_id,
        service_date=menu_day.service_date,
        # Legacy fields (for backward compat)
        regular_meal_count=program.total_children - program.vegan_count,
        vegan_meal_count=program.vegan_count,
        # Per-meal counts
        breakfast_count=breakfast_count if menu_day.breakfast_item_id else None,
        breakfast_vegan_count=breakfast_vegan if menu_day.breakfast_item_id else 0,
        lunch_count=lunch_count - lunch_vegan if menu_day.lunch_item_id else None,
        lunch_vegan_count=lunch_vegan if menu_day.lunch_item_id else 0,
        snack_count=snack_count if menu_day.snack_item_id else None,
        snack_vegan_count=0,  # Snack vegan not tracked
        tenant_id=tenant_id
    )

    return await create_invoice(db, invoice_data)


async def generate_bulk_invoices_for_month(db: AsyncSession, monthly_menu_id: str, tenant_id: int):
    """Generate invoices for all menu days in a monthly menu"""
    from .monthly_menu import get_monthly_menu

    monthly_menu = await get_monthly_menu(db, monthly_menu_id, tenant_id)
    if not monthly_menu:
        return []

    generated_invoices = []
    for menu_day in monthly_menu.menu_days:
        # Only generate if has meals assigned
        if menu_day.breakfast_item_id or menu_day.lunch_item_id or menu_day.snack_item_id:
            invoice = await generate_invoice_from_menu_day(db, menu_day.id, tenant_id)
            if invoice:
                generated_invoices.append(invoice)

    return generated_invoices


async def delete_invoice(db: AsyncSession, invoice_id: str, tenant_id: int):
    """Delete an invoice"""
    invoice = await get_invoice(db, invoice_id, tenant_id)
    if invoice:
        await db.delete(invoice)
        await db.commit()
    return invoice
