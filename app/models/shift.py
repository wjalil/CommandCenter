from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Integer
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid
from datetime import datetime
from app.models.tenant import Tenant
from app.models.task import TaskSubmission

class Shift(Base):
    __tablename__ = "shifts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    label = Column(String, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    date = Column(DateTime, default=datetime.utcnow)

    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    tenant = relationship("Tenant", back_populates="shifts")

    is_filled = Column(Boolean, default=False)
    is_completed = Column(Boolean, default=False)     # ✅ NEW
    is_recurring = Column(Boolean, default=False)     # ✅ NEW

    shift_type = Column(String, nullable=True)  # 🆕 Shift type (e.g. 'Store', 'Driver')

    assigned_worker_id = Column(String, ForeignKey("users.id"), nullable=True)
    worker = relationship("User", back_populates="shifts")

    submissions = relationship("TaskSubmission",back_populates="shift",cascade="all, delete-orphan", passive_deletes=True)

    tasks = relationship("Task", back_populates="shift")

    # ✅ New fields
    recurring_until = Column(DateTime, nullable=True)
    is_seed = Column(Boolean, default=True)
    recurring_group_id = Column(String, nullable=True)