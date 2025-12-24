from sqlalchemy import Column, Integer, String, Numeric, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.models.base import Base


class CACFPAgeGroup(Base):
    __tablename__ = "cacfp_age_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    age_min_months = Column(Integer, nullable=False)
    age_max_months = Column(Integer, nullable=True)
    sort_order = Column(Integer, nullable=False)

    portion_rules = relationship("CACFPPortionRule", back_populates="age_group")
    programs = relationship("CateringProgram", back_populates="age_group")


class CACFPComponentType(Base):
    __tablename__ = "cacfp_component_types"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False)

    portion_rules = relationship("CACFPPortionRule", back_populates="component_type")
    food_components = relationship("FoodComponent", back_populates="component_type")


class CACFPPortionRule(Base):
    __tablename__ = "cacfp_portion_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    age_group_id = Column(Integer, ForeignKey("cacfp_age_groups.id"), nullable=False)
    component_type_id = Column(Integer, ForeignKey("cacfp_component_types.id"), nullable=False)
    meal_type = Column(String, nullable=False)  # Breakfast, Lunch, Snack
    min_portion_oz = Column(Numeric(5, 2), nullable=False)
    max_portion_oz = Column(Numeric(5, 2), nullable=True)
    notes = Column(Text, nullable=True)

    age_group = relationship("CACFPAgeGroup", back_populates="portion_rules")
    component_type = relationship("CACFPComponentType", back_populates="portion_rules")

    __table_args__ = (
        UniqueConstraint("age_group_id", "component_type_id", "meal_type", name="uq_portion_rule"),
    )
