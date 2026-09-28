from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, DateTime, Date, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid


class CateringMasterMenu(Base):
    """
    One tenant-wide menu for a month, built once (usually from an uploaded CSV) and
    published into every program's CateringMonthlyMenu. Program menus stay the source
    of truth for production, invoices and the portal; the master menu only feeds them.
    """
    __tablename__ = "catering_master_menus"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String, nullable=False, default="Standard")  # lets a kitchen run e.g. "Standard" + "Infant"
    month = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    status = Column(String, default="draft", nullable=False)  # draft, published
    source_filename = Column(String, nullable=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    days = relationship(
        "CateringMasterMenuDay", back_populates="master_menu",
        cascade="all, delete-orphan", order_by="CateringMasterMenuDay.service_date",
    )
    program_menus = relationship("CateringMonthlyMenu", back_populates="master_menu")

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "month", "year", name="uq_master_menu"),
        Index("idx_master_menus_tenant", "tenant_id", "year", "month"),
    )


class CateringMasterMenuDay(Base):
    __tablename__ = "catering_master_menu_days"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    master_menu_id = Column(String, ForeignKey("catering_master_menus.id", ondelete="CASCADE"), nullable=False)
    service_date = Column(Date, nullable=False)
    is_closed = Column(Boolean, default=False, nullable=False)  # "OFF" in the sheet: kitchen doesn't serve anyone
    closed_reason = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    master_menu = relationship("CateringMasterMenu", back_populates="days")
    components = relationship(
        "CateringMasterMenuComponent", back_populates="day",
        cascade="all, delete-orphan", order_by="CateringMasterMenuComponent.sort_order",
    )

    __table_args__ = (
        UniqueConstraint("master_menu_id", "service_date", name="uq_master_menu_day"),
    )


class CateringMasterMenuComponent(Base):
    __tablename__ = "catering_master_menu_components"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    day_id = Column(String, ForeignKey("catering_master_menu_days.id", ondelete="CASCADE"), nullable=False)
    component_id = Column(Integer, ForeignKey("food_components.id"), nullable=False)
    meal_slot = Column(String, nullable=False)  # breakfast, lunch, snack, am_snack, pm_snack
    is_vegan = Column(Boolean, default=False, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    day = relationship("CateringMasterMenuDay", back_populates="components")
    food_component = relationship("FoodComponent")

    __table_args__ = (
        UniqueConstraint("day_id", "component_id", "meal_slot", "is_vegan", name="uq_master_menu_component"),
        Index("idx_master_menu_components_day", "day_id"),
    )
