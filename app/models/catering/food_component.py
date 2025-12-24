from sqlalchemy import Column, Integer, String, Numeric, Boolean, ForeignKey, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base


class FoodComponent(Base):
    __tablename__ = "food_components"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    component_type_id = Column(Integer, ForeignKey("cacfp_component_types.id"), nullable=False)
    default_portion_oz = Column(Numeric(5, 2), nullable=False)
    is_vegan = Column(Boolean, default=False, nullable=False)
    is_vegetarian = Column(Boolean, default=True, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    component_type = relationship("CACFPComponentType", back_populates="food_components")
    tenant = relationship("Tenant", back_populates="food_components")
    meal_components = relationship("CateringMealComponent", back_populates="food_component")

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_food_component_tenant_name"),
        Index("idx_food_components_tenant", "tenant_id"),
        Index("idx_food_components_type", "component_type_id"),
    )
