from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Date, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid


class CateringInvoice(Base):
    """Daily delivery invoice/receipt showing CACFP portions (no pricing)"""
    __tablename__ = "catering_invoices"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_number = Column(String, nullable=False)  # BC001, BC002, LC001, etc.
    program_id = Column(String, ForeignKey("catering_programs.id"), nullable=False)
    monthly_menu_id = Column(String, ForeignKey("catering_monthly_menus.id"), nullable=True)
    menu_day_id = Column(String, ForeignKey("catering_menu_days.id"), nullable=True)
    service_date = Column(Date, nullable=False)
    regular_meal_count = Column(Integer, nullable=False)
    vegan_meal_count = Column(Integer, default=0, nullable=False)
    status = Column(String, default="draft", nullable=False)  # draft, finalized, sent
    pdf_filename = Column(String, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

    program = relationship("CateringProgram", back_populates="invoices")
    monthly_menu = relationship("CateringMonthlyMenu", back_populates="invoices")
    menu_day = relationship("CateringMenuDay", back_populates="invoices")
    tenant = relationship("Tenant", back_populates="catering_invoices")

    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_number", name="uq_invoice_number"),
        Index("idx_invoices_tenant", "tenant_id"),
        Index("idx_invoices_program", "program_id"),
        Index("idx_invoices_service_date", "service_date"),
    )
