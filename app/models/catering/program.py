from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, Text, DateTime, Date, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid


class CateringProgram(Base):
    __tablename__ = "catering_programs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    client_name = Column(String, nullable=False)
    client_email = Column(String, nullable=True)
    client_phone = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    age_group_id = Column(Integer, ForeignKey("cacfp_age_groups.id"), nullable=False)
    total_children = Column(Integer, nullable=False)
    vegan_count = Column(Integer, default=0, nullable=False)
    invoice_prefix = Column(String, nullable=False)  # BC, LC, etc.
    last_invoice_number = Column(Integer, default=0, nullable=False)
    service_days = Column(String, nullable=False)  # JSON: ["Monday", "Tuesday", ...]
    meal_types_required = Column(String, nullable=False)  # JSON: ["breakfast", "lunch", "snack"]
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    age_group = relationship("CACFPAgeGroup", back_populates="programs")
    tenant = relationship("Tenant", back_populates="catering_programs")
    holidays = relationship("CateringProgramHoliday", back_populates="program", cascade="all, delete-orphan")
    monthly_menus = relationship("CateringMonthlyMenu", back_populates="program", cascade="all, delete-orphan")
    invoices = relationship("CateringInvoice", back_populates="program")

    __table_args__ = (
        Index("idx_catering_programs_tenant", "tenant_id"),
        Index("idx_catering_programs_active", "tenant_id", "is_active"),
    )


class CateringProgramHoliday(Base):
    __tablename__ = "catering_program_holidays"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id = Column(String, ForeignKey("catering_programs.id", ondelete="CASCADE"), nullable=False)
    holiday_date = Column(Date, nullable=False)
    description = Column(String, nullable=True)

    program = relationship("CateringProgram", back_populates="holidays")

    __table_args__ = (
        UniqueConstraint("program_id", "holiday_date", name="uq_program_holiday"),
        Index("idx_program_holidays_program", "program_id"),
    )
