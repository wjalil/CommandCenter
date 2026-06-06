from sqlalchemy import Column, String, ForeignKey, Numeric, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid


class DeliveryRoutePayRate(Base):
    """Per-driver pay rate for a route template. Stamped onto daily routes at generation."""
    __tablename__ = "delivery_route_pay_rates"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    template_id = Column(String, ForeignKey("delivery_route_templates.id", ondelete="CASCADE"), nullable=False)
    driver_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    pay_rate = Column(Numeric(10, 2), nullable=False)

    template = relationship("DeliveryRouteTemplate", back_populates="pay_rates")
    driver = relationship("User")

    __table_args__ = (
        UniqueConstraint("template_id", "driver_id", name="uq_route_pay_rate"),
        Index("idx_route_pay_rates_template", "template_id"),
    )
