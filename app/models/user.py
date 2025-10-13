from sqlalchemy import Column, String, Boolean,Integer,ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid
from app.models.shortage_log import ShortageLog
from app.models.custom_modules.vending_log import VendingLog
from sqlalchemy import Numeric

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    pin_code = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "admin", "worker"
    #Tenant ID 
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    tenant = relationship("Tenant", back_populates="users")

    worker_type = Column(String, nullable=True) 
    is_active = Column(Boolean, default=True)
    business_id = Column(String, nullable=True)  # just store it raw for now
    shifts = relationship("Shift", back_populates="worker")
    submissions = relationship("TaskSubmission", back_populates="worker")
    vending_logs = relationship("VendingLog", back_populates="submitter", cascade="all, delete-orphan")
    hourly_rate = Column(Numeric(10,2), nullable=True) # per-tenant rate