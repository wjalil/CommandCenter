from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, DateTime, Date, Text, Numeric, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid


class CateringSubstitution(Base):
    """A same-day swap of one food component for another, made on the Production
    Sheet ("the chicken didn't come in, every lunch gets turkey"). Layered on top
    of the planned menu rather than editing it, so the plan stays intact and the
    record shows what was planned, what was served, and why.

    Scope: program_id NULL = every program serving that meal that day; otherwise
    just that program. meal_slot NULL = every slot the original appears in. The
    most specific matching row wins (program beats kitchen-wide, slot beats any)."""
    __tablename__ = "catering_substitutions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    service_date = Column(Date, nullable=False)
    meal_slot = Column(String, nullable=True)  # breakfast, lunch, snack, am_snack, pm_snack; NULL = any
    is_vegan = Column(Boolean, default=False, nullable=False)
    program_id = Column(String, ForeignKey("catering_programs.id", ondelete="CASCADE"), nullable=True)  # NULL = all programs
    original_component_id = Column(Integer, ForeignKey("food_components.id"), nullable=False)
    replacement_component_id = Column(Integer, ForeignKey("food_components.id"), nullable=False)
    portion_oz = Column(Numeric(5, 2), nullable=True)  # NULL = keep the planned portion (or the replacement's default if the type changed)
    reason = Column(Text, nullable=True)
    created_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    program = relationship("CateringProgram")
    original_component = relationship("FoodComponent", foreign_keys=[original_component_id])
    replacement_component = relationship("FoodComponent", foreign_keys=[replacement_component_id])

    __table_args__ = (
        Index("idx_substitutions_tenant_date", "tenant_id", "service_date"),
    )
