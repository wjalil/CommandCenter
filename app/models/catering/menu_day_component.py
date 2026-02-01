from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Text, Boolean, Numeric, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from datetime import datetime
from app.models.base import Base
import uuid


class MenuDayComponent(Base):
    """
    Associates individual FoodComponents directly with a CateringMenuDay.
    This allows component-first menu building without pre-creating MealItem combinations.
    """
    __tablename__ = "menu_day_components"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    menu_day_id = Column(String, ForeignKey("catering_menu_days.id", ondelete="CASCADE"), nullable=False)
    component_id = Column(Integer, ForeignKey("food_components.id"), nullable=False)
    meal_slot = Column(String, nullable=False)  # breakfast, lunch, snack
    is_vegan = Column(Boolean, default=False, nullable=False)
    quantity = Column(Numeric(5, 2), nullable=True)  # Optional portion override
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    menu_day = relationship("CateringMenuDay", back_populates="components")
    food_component = relationship("FoodComponent", back_populates="menu_day_components")

    # Computed properties for Pydantic serialization
    @hybrid_property
    def component_name(self) -> str:
        """Get the food component name for serialization"""
        if self.food_component:
            return self.food_component.name
        return ""

    @hybrid_property
    def component_type(self) -> str:
        """Get the food component type name for serialization"""
        if self.food_component and self.food_component.component_type:
            return self.food_component.component_type.name
        return ""

    __table_args__ = (
        UniqueConstraint("menu_day_id", "component_id", "meal_slot", "is_vegan", name="uq_menu_day_component"),
        Index("idx_menu_day_components_day", "menu_day_id"),
        Index("idx_menu_day_components_slot", "menu_day_id", "meal_slot"),
    )
