from sqlalchemy import Column, String, Integer, ForeignKey, Text, DateTime, Index
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid


class DeliveryRouteStop(Base):
    """Junction table linking routes to stops with tracking data"""
    __tablename__ = "delivery_route_stops"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    route_id = Column(String, ForeignKey("delivery_routes.id", ondelete="CASCADE"), nullable=False)
    stop_id = Column(String, ForeignKey("delivery_stops.id", ondelete="CASCADE"), nullable=False)
    stop_order = Column(Integer, nullable=False)
    status = Column(String, default="pending", nullable=False)  # pending, completed, skipped
    arrival_time = Column(DateTime, nullable=True)
    departure_time = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    photo_filename = Column(String, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    route = relationship("DeliveryRoute", back_populates="route_stops")
    stop = relationship("DeliveryStop", back_populates="route_stops")

    __table_args__ = (
        Index("idx_route_stops_route", "route_id"),
        Index("idx_route_stops_stop", "stop_id"),
    )
