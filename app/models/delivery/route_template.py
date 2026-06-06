from sqlalchemy import Column, String, Integer, ForeignKey, Text, DateTime, Boolean, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class DeliveryRouteTemplate(Base):
    __tablename__ = "delivery_route_templates"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="delivery_route_templates")
    template_stops = relationship(
        "DeliveryRouteTemplateStop",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="DeliveryRouteTemplateStop.stop_order",
    )
    template_days = relationship(
        "DeliveryRouteTemplateDay",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="DeliveryRouteTemplateDay.day_of_week",
    )
    pay_rates = relationship(
        "DeliveryRoutePayRate",
        back_populates="template",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_route_templates_tenant", "tenant_id"),
    )

    @property
    def active_day_names(self):
        return [DAY_NAMES[d.day_of_week] for d in self.template_days]


class DeliveryRouteTemplateStop(Base):
    __tablename__ = "delivery_route_template_stops"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    template_id = Column(String, ForeignKey("delivery_route_templates.id", ondelete="CASCADE"), nullable=False)
    stop_id = Column(String, ForeignKey("delivery_stops.id"), nullable=False)
    stop_order = Column(Integer, nullable=False)

    template = relationship("DeliveryRouteTemplate", back_populates="template_stops")
    stop = relationship("DeliveryStop")

    __table_args__ = (
        Index("idx_template_stops_template", "template_id"),
    )


class DeliveryRouteTemplateDay(Base):
    __tablename__ = "delivery_route_template_days"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    template_id = Column(String, ForeignKey("delivery_route_templates.id", ondelete="CASCADE"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Monday … 6=Sunday
    driver_id = Column(String, ForeignKey("users.id"), nullable=True)

    template = relationship("DeliveryRouteTemplate", back_populates="template_days")
    driver = relationship("User")

    __table_args__ = (
        UniqueConstraint("template_id", "day_of_week", name="uq_template_day"),
        Index("idx_template_days_template", "template_id"),
    )

    @property
    def day_name(self):
        return DAY_NAMES[self.day_of_week]
