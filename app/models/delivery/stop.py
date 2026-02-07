from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, Text, Index
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid


class DeliveryStop(Base):
    """Reusable delivery stop locations"""
    __tablename__ = "delivery_stops"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    address = Column(String, nullable=True)
    contact_name = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)

    tenant = relationship("Tenant", back_populates="delivery_stops")
    route_stops = relationship("DeliveryRouteStop", back_populates="stop", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_delivery_stops_tenant", "tenant_id"),
        Index("idx_delivery_stops_active", "tenant_id", "is_active"),
    )
