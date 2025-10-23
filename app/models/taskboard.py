from sqlalchemy import (
    Column, String, DateTime, Boolean, Integer, ForeignKey, Date,
    SmallInteger, CheckConstraint, Index, Text
)

from sqlalchemy.orm import relationship
from app.models.base import Base
from datetime import datetime, date
import uuid
import enum

class DayOfWeek(enum.IntEnum):
    MON=1; TUE=2; WED=3; THU=4; FRI=5; SAT=6; SUN=7

class DailyTask(Base):
    __tablename__ = "daily_tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)

    # Core content
    title = Column(String, nullable=False)           # e.g., “Package 80 breakfasts”
    details = Column(String, nullable=True)          # e.g., “use bin C for snacks”

    # ✅ Quantities are OPTIONAL
    target_qty   = Column(Integer, nullable=True)    # expected qty, e.g., 55 (NULL if N/A)
    progress_qty = Column(Integer, nullable=True)    # partial qty, e.g., 35 (NULL if unused)
    progress_note = Column(Text, nullable=True)      # free text note (optional)

    # Scheduling / grouping
    task_date = Column(Date, nullable=True)          # preferred exact date
    day_of_week = Column(SmallInteger, nullable=True)  # 1–7 quick filter
    shift_label = Column(String, nullable=True)      # "Morning Open", "Delivery", etc.
    role = Column(String, nullable=True)             # "Barista", "Inventory", etc.

    # Completion (independent of quantities)
    is_completed = Column(Boolean, default=False, nullable=False)
    completed_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Audit / ordering
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    order_index = Column(SmallInteger, default=0)

    # Relationships
    tenant = relationship("Tenant")
    completed_by = relationship("User", foreign_keys=[completed_by_id])

    # Guardrails + helpful index
    __table_args__ = (
        CheckConstraint("target_qty IS NULL OR target_qty >= 0", name="ck_daily_tasks_target_qty_nonneg"),
        CheckConstraint("progress_qty IS NULL OR progress_qty >= 0", name="ck_daily_tasks_progress_qty_nonneg"),
        CheckConstraint(
            "(target_qty IS NULL) OR (progress_qty IS NULL) OR (progress_qty <= target_qty)",
            name="ck_daily_tasks_progress_le_target"
        ),
        Index("ix_daily_tasks_tenant_date_completed", "tenant_id", "task_date", "is_completed"),
    )
