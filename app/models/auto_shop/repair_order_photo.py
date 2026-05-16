from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Index
from sqlalchemy.orm import relationship
from app.models.base import Base
from datetime import datetime
import uuid


class RepairOrderPhoto(Base):
    __tablename__ = "repair_order_photos"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    repair_order_id = Column(
        String, ForeignKey("repair_orders.id", ondelete="CASCADE"), nullable=False
    )
    filename = Column(String, nullable=False)           # UUID-safe name on disk
    original_filename = Column(String, nullable=False)  # original upload name
    caption = Column(String, nullable=True)
    category = Column(String, nullable=True)            # intake | damage | in_progress | completed
    uploaded_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)

    repair_order = relationship("RepairOrder", back_populates="photos")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])

    __table_args__ = (
        Index("idx_repair_photos_order", "repair_order_id"),
        Index("idx_repair_photos_tenant", "tenant_id"),
    )
