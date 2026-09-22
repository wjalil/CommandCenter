from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Date, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid


class CateringDailyCount(Base):
    """Same-day override of a program's meal-slot headcount, edited on the Production
    Sheet (e.g. "22 kids today, not the usual 25"). Only holds exceptions — invoice
    and kitchen-prep logic fall back to the program's standing count (e.g.
    program.lunch_count) whenever no row exists for a given (program, date, slot)."""
    __tablename__ = "catering_daily_counts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    program_id = Column(String, ForeignKey("catering_programs.id", ondelete="CASCADE"), nullable=False)
    service_date = Column(Date, nullable=False)
    meal_slot = Column(String, nullable=False)  # breakfast, lunch, snack, am_snack, pm_snack
    count = Column(Integer, nullable=False)
    vegan_count = Column(Integer, default=0, nullable=False)
    updated_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    program = relationship("CateringProgram")

    __table_args__ = (
        UniqueConstraint("program_id", "service_date", "meal_slot", name="uq_daily_count_program_date_slot"),
        Index("idx_daily_counts_program_date", "program_id", "service_date"),
        Index("idx_daily_counts_tenant_date", "tenant_id", "service_date"),
    )
