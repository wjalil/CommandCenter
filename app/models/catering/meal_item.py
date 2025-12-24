from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, Text, DateTime, Numeric, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid


class CateringMealItem(Base):
    __tablename__ = "catering_meal_items"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    meal_type = Column(String, nullable=False)  # Breakfast, Lunch, Snack
    is_vegan = Column(Boolean, default=False, nullable=False)
    is_vegetarian = Column(Boolean, default=False, nullable=False)
    photo_filename = Column(String, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="catering_meal_items")
    components = relationship("CateringMealComponent", back_populates="meal_item", cascade="all, delete-orphan")

    # Menu day relationships
    menu_days_breakfast = relationship("CateringMenuDay", foreign_keys="CateringMenuDay.breakfast_item_id", back_populates="breakfast_item")
    menu_days_breakfast_vegan = relationship("CateringMenuDay", foreign_keys="CateringMenuDay.breakfast_vegan_item_id", back_populates="breakfast_vegan_item")
    menu_days_lunch = relationship("CateringMenuDay", foreign_keys="CateringMenuDay.lunch_item_id", back_populates="lunch_item")
    menu_days_lunch_vegan = relationship("CateringMenuDay", foreign_keys="CateringMenuDay.lunch_vegan_item_id", back_populates="lunch_vegan_item")
    menu_days_snack = relationship("CateringMenuDay", foreign_keys="CateringMenuDay.snack_item_id", back_populates="snack_item")
    menu_days_snack_vegan = relationship("CateringMenuDay", foreign_keys="CateringMenuDay.snack_vegan_item_id", back_populates="snack_vegan_item")

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_meal_item_tenant_name"),
        Index("idx_catering_meal_items_tenant", "tenant_id"),
        Index("idx_catering_meal_items_type", "meal_type"),
    )


class CateringMealComponent(Base):
    __tablename__ = "catering_meal_components"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    meal_item_id = Column(String, ForeignKey("catering_meal_items.id", ondelete="CASCADE"), nullable=False)
    food_component_id = Column(Integer, ForeignKey("food_components.id"), nullable=False)
    portion_oz = Column(Numeric(5, 2), nullable=False)

    meal_item = relationship("CateringMealItem", back_populates="components")
    food_component = relationship("FoodComponent", back_populates="meal_components")

    __table_args__ = (
        UniqueConstraint("meal_item_id", "food_component_id", name="uq_meal_component"),
        Index("idx_meal_components_meal", "meal_item_id"),
    )
