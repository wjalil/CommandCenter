from sqlalchemy import Column, String, DateTime, ForeignKey, Text , Integer
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid
from datetime import datetime

class VendingLog(Base):
    __tablename__ = "vending_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    photo_filename = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    submitter_id = Column(String, ForeignKey("users.id"), nullable=True)

    submitter = relationship("User", back_populates="vending_logs")

    machine_id = Column(String, ForeignKey("machines.id"), nullable=True)
    machine = relationship("Machine")
    issue_type = Column(String, nullable=False)
    source = Column(String, default="internal") 
    email = Column(String, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    tenant = relationship("Tenant", back_populates="vending_logs")

