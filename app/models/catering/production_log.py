from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Date, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid


class ProductionDailyLog(Base):
    __tablename__ = "catering_production_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    service_date = Column(Date, nullable=False)
    # NULL program_id = kitchen prep item (not program-specific)
    program_id = Column(String, ForeignKey("catering_programs.id", ondelete="CASCADE"), nullable=True)
    # 'produce', 'milk', 'juice' for supply checks (requires program_id)
    # 'prep' for kitchen component checks (program_id = null)
    check_type = Column(String, nullable=False)
    # For 'prep' checks: the food component name (e.g. "Brown Rice")
    reference_key = Column(String, nullable=True)
    checked_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    checked_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    program = relationship("CateringProgram", back_populates="production_logs")

    __table_args__ = (
        Index("idx_production_logs_date", "tenant_id", "service_date"),
        Index("idx_production_logs_program", "program_id"),
    )
