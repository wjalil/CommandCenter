from sqlalchemy import Column, String, DateTime, Boolean , Integer , ForeignKey 
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid
from datetime import datetime


class ShortageLog(Base):
    __tablename__ = "shortage_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    note = Column(String, nullable=False)
    is_resolved = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    tenant = relationship("Tenant", back_populates="shortage_logs")