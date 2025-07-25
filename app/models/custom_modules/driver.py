# 1. MODELS: app/models/custom_modules/driver_order.py

from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid
from datetime import datetime

class DriverOrder(Base):
    __tablename__ = "driver_orders"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    shift_id = Column(String, ForeignKey("shifts.id"), nullable=False)
    photo_url = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    shift = relationship("Shift", back_populates="driver_orders")

# Optional: add back_populates to Shift model if needed
# In app/models/shift.py:
# driver_orders = relationship("DriverOrder", back_populates="shift")
