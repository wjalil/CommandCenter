from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Date, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid


class CateringMonthlyMenu(Base):
    __tablename__ = "catering_monthly_menus"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id = Column(String, ForeignKey("catering_programs.id"), nullable=False)
    month = Column(Integer, nullable=False)  # 1-12
    year = Column(Integer, nullable=False)
    status = Column(String, default="draft", nullable=False)  # draft, finalized, sent
    finalized_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    program = relationship("CateringProgram", back_populates="monthly_menus")
    tenant = relationship("Tenant", back_populates="catering_monthly_menus")
    menu_days = relationship("CateringMenuDay", back_populates="monthly_menu", cascade="all, delete-orphan")
    invoices = relationship("CateringInvoice", back_populates="monthly_menu")

    __table_args__ = (
        UniqueConstraint("program_id", "month", "year", name="uq_monthly_menu"),
        Index("idx_monthly_menus_tenant", "tenant_id"),
        Index("idx_monthly_menus_program", "program_id", "year", "month"),
    )


class CateringMenuDay(Base):
    __tablename__ = "catering_menu_days"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    monthly_menu_id = Column(String, ForeignKey("catering_monthly_menus.id", ondelete="CASCADE"), nullable=False)
    service_date = Column(Date, nullable=False)

    # Breakfast
    breakfast_item_id = Column(String, ForeignKey("catering_meal_items.id"), nullable=True)
    breakfast_vegan_item_id = Column(String, ForeignKey("catering_meal_items.id"), nullable=True)

    # Lunch
    lunch_item_id = Column(String, ForeignKey("catering_meal_items.id"), nullable=True)
    lunch_vegan_item_id = Column(String, ForeignKey("catering_meal_items.id"), nullable=True)

    # Snack
    snack_item_id = Column(String, ForeignKey("catering_meal_items.id"), nullable=True)
    snack_vegan_item_id = Column(String, ForeignKey("catering_meal_items.id"), nullable=True)

    notes = Column(Text, nullable=True)

    monthly_menu = relationship("CateringMonthlyMenu", back_populates="menu_days")

    # Meal item relationships
    breakfast_item = relationship("CateringMealItem", foreign_keys=[breakfast_item_id], back_populates="menu_days_breakfast")
    breakfast_vegan_item = relationship("CateringMealItem", foreign_keys=[breakfast_vegan_item_id], back_populates="menu_days_breakfast_vegan")
    lunch_item = relationship("CateringMealItem", foreign_keys=[lunch_item_id], back_populates="menu_days_lunch")
    lunch_vegan_item = relationship("CateringMealItem", foreign_keys=[lunch_vegan_item_id], back_populates="menu_days_lunch_vegan")
    snack_item = relationship("CateringMealItem", foreign_keys=[snack_item_id], back_populates="menu_days_snack")
    snack_vegan_item = relationship("CateringMealItem", foreign_keys=[snack_vegan_item_id], back_populates="menu_days_snack_vegan")

    invoices = relationship("CateringInvoice", back_populates="menu_day")
    components = relationship("MenuDayComponent", back_populates="menu_day", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("monthly_menu_id", "service_date", name="uq_menu_day"),
        Index("idx_menu_days_monthly", "monthly_menu_id"),
        Index("idx_menu_days_date", "service_date"),
    )
