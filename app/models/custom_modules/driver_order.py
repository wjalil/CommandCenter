# app/models/custom_modules/driver_order.py

from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid
from datetime import datetime

class DriverOrder(Base):
    __tablename__ = "driver_order"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    notes = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    photo_filename = Column(String, nullable=True)
    is_resolved = Column(Boolean, default=False)







