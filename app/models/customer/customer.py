from sqlalchemy import Column, String, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid

class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    pin_code = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    tenant = relationship("Tenant", back_populates="customers")

    orders = relationship("CustomerOrder", back_populates="customer", cascade="all, delete-orphan")

    # Security: Prevent PIN collision between tenants
    __table_args__ = (
        UniqueConstraint("tenant_id", "pin_code", name="uq_customer_tenant_pin"),
    )
