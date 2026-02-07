from sqlalchemy import Column, String, Integer, ForeignKey, Text, DateTime, Date, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid


class DeliveryRoute(Base):
    """Daily delivery routes"""
    __tablename__ = "delivery_routes"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    assigned_driver_id = Column(String, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="draft", nullable=False)  # draft, assigned, in_progress, completed
    notes = Column(Text, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="delivery_routes")
    assigned_driver = relationship("User", back_populates="assigned_routes")
    route_stops = relationship(
        "DeliveryRouteStop",
        back_populates="route",
        cascade="all, delete-orphan",
        order_by="DeliveryRouteStop.stop_order"
    )

    __table_args__ = (
        Index("idx_delivery_routes_tenant", "tenant_id"),
        Index("idx_delivery_routes_date", "tenant_id", "date"),
        Index("idx_delivery_routes_driver", "assigned_driver_id"),
    )
