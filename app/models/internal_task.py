from sqlalchemy import Column, String, Boolean,Integer,ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid

class InternalTask(Base):
    __tablename__ = "internal_tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    is_completed = Column(Boolean, default=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    tenant = relationship("Tenant", back_populates="internal_tasks")    
