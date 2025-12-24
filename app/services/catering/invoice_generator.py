"""
Invoice Generation Service

Generates catering invoices with:
- Auto-incrementing invoice numbers
- Meal counts (regular + vegan)
- Service date information
- Program details
- PDF generation (optional)
"""
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.catering import CateringProgram, CateringMenuDay
from app.crud.catering import invoice as invoice_crud
from app.schemas.catering import CateringInvoiceCreate
from datetime import date
from typing import Optional


class InvoiceGenerator:
    """Generates catering invoices"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_invoice_for_date(
        self,
        program_id: str,
        service_date: date,
        menu_day_id: Optional[str] = None,
        monthly_menu_id: Optional[str] = None,
        regular_meal_count: Optional[int] = None,
        vegan_meal_count: Optional[int] = None
    ):
        """
        Generate an invoice for a specific service date.

        Args:
            program_id: The catering program
            service_date: Date of service
            menu_day_id: Optional menu day ID
            monthly_menu_id: Optional monthly menu ID
            regular_meal_count: Number of regular meals (defaults to program total - vegan count)
            vegan_meal_count: Number of vegan meals (defaults to program vegan_count)

        Returns:
            Created CateringInvoice
        """
        # Get program
        program = await self.db.get(CateringProgram, program_id)
        if not program:
            raise ValueError(f"Program {program_id} not found")

        # Default meal counts from program
        if regular_meal_count is None:
            regular_meal_count = program.total_children - program.vegan_count

        if vegan_meal_count is None:
            vegan_meal_count = program.vegan_count

        # Create invoice
        invoice_create = CateringInvoiceCreate(
            program_id=program_id,
            service_date=service_date,
            regular_meal_count=regular_meal_count,
            vegan_meal_count=vegan_meal_count,
            monthly_menu_id=monthly_menu_id,
            menu_day_id=menu_day_id,
            tenant_id=program.tenant_id
        )

        invoice = await invoice_crud.create_invoice(self.db, invoice_create)
        return invoice

    async def generate_invoices_for_month(
        self,
        monthly_menu_id: str
    ):
        """
        Generate invoices for all service dates in a monthly menu.

        Returns:
            List of created invoices
        """
        from app.models.catering import CateringMonthlyMenu
        from sqlalchemy.orm import selectinload

        # Get monthly menu with all menu days
        from sqlalchemy.future import select
        result = await self.db.execute(
            select(CateringMonthlyMenu)
            .where(CateringMonthlyMenu.id == monthly_menu_id)
            .options(
                selectinload(CateringMonthlyMenu.menu_days),
                selectinload(CateringMonthlyMenu.program)
            )
        )
        monthly_menu = result.scalar_one_or_none()

        if not monthly_menu:
            raise ValueError(f"Monthly menu {monthly_menu_id} not found")

        program = monthly_menu.program
        invoices = []

        # Generate invoice for each menu day
        for menu_day in monthly_menu.menu_days:
            invoice = await self.generate_invoice_for_date(
                program_id=program.id,
                service_date=menu_day.service_date,
                menu_day_id=menu_day.id,
                monthly_menu_id=monthly_menu_id
            )
            invoices.append(invoice)

        return invoices

    def calculate_invoice_total(
        self,
        regular_meal_count: int,
        vegan_meal_count: int,
        regular_price: float = 5.00,
        vegan_price: float = 5.50
    ) -> dict:
        """
        Calculate invoice totals.

        Note: Pricing can be customized per program in future versions.

        Returns:
            {
                "regular_subtotal": float,
                "vegan_subtotal": float,
                "total": float,
                "meal_breakdown": {...}
            }
        """
        regular_subtotal = regular_meal_count * regular_price
        vegan_subtotal = vegan_meal_count * vegan_price
        total = regular_subtotal + vegan_subtotal

        return {
            "regular_subtotal": regular_subtotal,
            "vegan_subtotal": vegan_subtotal,
            "total": total,
            "meal_breakdown": {
                "regular": {
                    "count": regular_meal_count,
                    "price_per_meal": regular_price,
                    "subtotal": regular_subtotal
                },
                "vegan": {
                    "count": vegan_meal_count,
                    "price_per_meal": vegan_price,
                    "subtotal": vegan_subtotal
                }
            }
        }

    async def generate_invoice_pdf(
        self,
        invoice_id: str,
        output_path: Optional[str] = None
    ):
        """
        Generate PDF for an invoice.

        This is a placeholder for future PDF generation using ReportLab or WeasyPrint.

        Args:
            invoice_id: Invoice to generate PDF for
            output_path: Where to save the PDF

        Returns:
            Path to generated PDF file
        """
        # TODO: Implement PDF generation
        # For now, return a placeholder
        raise NotImplementedError(
            "PDF generation will be implemented in a future phase. "
            "Consider using ReportLab, WeasyPrint, or a template-based approach."
        )
