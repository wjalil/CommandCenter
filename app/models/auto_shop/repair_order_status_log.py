from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, Text, DateTime, Index
from sqlalchemy.orm import relationship
from app.models.base import Base
from datetime import datetime
import uuid


class RepairOrderStatusLog(Base):
    __tablename__ = "repair_order_status_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    repair_order_id = Column(
        String, ForeignKey("repair_orders.id", ondelete="CASCADE"), nullable=False
    )
    old_status = Column(String, nullable=True)
    new_status = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    changed_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    changed_at = Column(DateTime, default=datetime.utcnow)
    sms_sent = Column(Boolean, default=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)

    repair_order = relationship("RepairOrder", back_populates="status_logs")
    changed_by = relationship("User", foreign_keys=[changed_by_id])

    __table_args__ = (
        Index("idx_status_logs_order", "repair_order_id"),
        Index("idx_status_logs_tenant", "tenant_id"),
    )
