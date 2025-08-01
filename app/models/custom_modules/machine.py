from sqlalchemy import Column, String, ForeignKey, Integer
from app.models.base import Base
import uuid
from sqlalchemy.orm import relationship

class Machine(Base):
    __tablename__ = "machines"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, nullable=False)  # e.g. “Union Square Gym”
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    tenant = relationship("Tenant", back_populates="machines")  
