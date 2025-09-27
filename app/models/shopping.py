import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Boolean, ForeignKey, DateTime, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.models.base import Base

class BusinessLine(Base):
    __tablename__ = "business_lines"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_bl_tenant_name"),)

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_cat_tenant_name"),)

class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False)
    contact = Column(String)
    notes = Column(Text)
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_supplier_tenant_name"),)

class Item(Base):
    __tablename__ = "items"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(Integer, nullable=False, index=True)

    name = Column(String, nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"))
    business_line_id = Column(Integer, ForeignKey("business_lines.id", ondelete="SET NULL"))
    unit = Column(String, default="ea")
    par_level = Column(Integer, default=0)
    notes = Column(Text)
    default_supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="SET NULL"))

    category = relationship("Category")
    business_line = relationship("BusinessLine")
    default_supplier = relationship("Supplier")
    needs = relationship("ShoppingNeed", back_populates="item", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_item_tenant_name"),)

class ShoppingNeed(Base):
    __tablename__ = "shopping_needs"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(Integer, nullable=False, index=True)

    item_id = Column(String, ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    item = relationship("Item", back_populates="needs")

    needed = Column(Boolean, default=False, index=True)
    status = Column(String, nullable=False, default="NEEDED", index=True)  # NEEDED|ORDERED|PURCHASED|SKIPPED
    quantity = Column(Integer, default=1)

    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="SET NULL"))
    supplier = relationship("Supplier")

    notes = Column(Text)
    last_updated_by = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "item_id", name="uq_need_tenant_item"),)

class ShoppingEvent(Base):
    __tablename__ = "shopping_events"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(Integer, nullable=False, index=True)
    item_id = Column(String, ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    from_status = Column(String)
    to_status = Column(String)
    quantity = Column(Integer, default=1)
    actor = Column(String)
    at = Column(DateTime, default=datetime.utcnow)
    note = Column(Text)
