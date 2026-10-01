from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, DateTime, Date, Text, Numeric, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid


class CateringInvoice(Base):
    """Daily Delivery Invoice (DDI) for one program on one service date — no pricing.

    What was delivered lives in `lines`, frozen when the invoice is built, so later
    menu edits never rewrite history. A draft is rebuilt freely; it locks
    (status 'finalized') when its route's manifest is released."""
    __tablename__ = "catering_invoices"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_number = Column(String, nullable=False)  # BC001, BC002, LC001, etc.
    program_id = Column(String, ForeignKey("catering_programs.id"), nullable=False)
    monthly_menu_id = Column(String, ForeignKey("catering_monthly_menus.id"), nullable=True)
    menu_day_id = Column(String, ForeignKey("catering_menu_days.id"), nullable=True)
    service_date = Column(Date, nullable=False)
    regular_meal_count = Column(Integer, nullable=False)  # Legacy - kept for backward compat
    vegan_meal_count = Column(Integer, default=0, nullable=False)  # Legacy - kept for backward compat

    # Per-meal counts for accurate invoicing
    breakfast_count = Column(Integer, nullable=True)
    breakfast_vegan_count = Column(Integer, default=0, nullable=False)
    lunch_count = Column(Integer, nullable=True)
    lunch_vegan_count = Column(Integer, default=0, nullable=False)
    snack_count = Column(Integer, nullable=True)
    snack_vegan_count = Column(Integer, default=0, nullable=False)
    am_snack_count = Column(Integer, nullable=True)
    am_snack_vegan_count = Column(Integer, default=0, nullable=False)
    pm_snack_count = Column(Integer, nullable=True)
    pm_snack_vegan_count = Column(Integer, default=0, nullable=False)

    # Snapshot of who/where at the time it was built — the program record can
    # change later, the delivery record must not.
    site_name = Column(String, nullable=True)
    site_address = Column(Text, nullable=True)
    client_name = Column(String, nullable=True)
    service_style = Column(String, nullable=True)  # family_style (bulk DDI) / individual (unitized DDI)
    is_cacfp = Column(Boolean, default=False, nullable=False)

    status = Column(String, default="draft", nullable=False)  # draft, finalized, sent
    finalized_at = Column(DateTime, nullable=True)
    pdf_filename = Column(String, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

    program = relationship("CateringProgram", back_populates="invoices")
    monthly_menu = relationship("CateringMonthlyMenu", back_populates="invoices")
    menu_day = relationship("CateringMenuDay", back_populates="invoices")
    tenant = relationship("Tenant", back_populates="catering_invoices")
    lines = relationship(
        "CateringInvoiceLine",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="CateringInvoiceLine.sort_order",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_number", name="uq_invoice_number"),
        Index("idx_invoices_tenant", "tenant_id"),
        Index("idx_invoices_program", "program_id"),
        Index("idx_invoices_service_date", "service_date"),
        Index("idx_invoices_program_date", "program_id", "service_date"),
    )


class CateringInvoiceLine(Base):
    """One food item delivered for one meal on an invoice, e.g. lunch / regular /
    Meat-Meat Alternate / Turkey / 2 oz each for 25 meals."""
    __tablename__ = "catering_invoice_lines"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_id = Column(String, ForeignKey("catering_invoices.id", ondelete="CASCADE"), nullable=False)
    meal_slot = Column(String, nullable=False)
    is_vegan = Column(Boolean, default=False, nullable=False)
    meal_count = Column(Integer, nullable=False)
    component_type = Column(String, nullable=True)  # CACFP component, e.g. "Grain", "Milk"
    item_name = Column(String, nullable=False)
    portion_qty = Column(Numeric(7, 2), nullable=True)
    portion_unit = Column(String, nullable=True)  # oz, fl oz, cup
    substituted_for = Column(String, nullable=True)  # planned item this replaced
    substitution_reason = Column(Text, nullable=True)
    is_auto = Column(Boolean, default=False, nullable=False)  # CACFP milk/fruit line added automatically
    sort_order = Column(Integer, default=0, nullable=False)

    invoice = relationship("CateringInvoice", back_populates="lines")

    __table_args__ = (
        Index("idx_invoice_lines_invoice", "invoice_id"),
    )
