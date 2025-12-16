from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base

class TenantModule(Base):
    __tablename__ = "tenant_modules"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    module_key = Column(String, nullable=False)   # e.g. "customer_ordering"
    enabled = Column(Boolean, nullable=False, default=True)

    tenant = relationship("Tenant")

    __table_args__ = (
        UniqueConstraint("tenant_id", "module_key", name="uq_tenant_module_key"),
    )
