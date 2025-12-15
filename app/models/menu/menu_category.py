from sqlalchemy import Column, String, Integer, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid

class MenuCategory(Base):
    __tablename__ = "menu_categories"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)

    menu_id = Column(String, ForeignKey("menus.id"), nullable=False)
    menu = relationship("Menu", back_populates="categories")

    name = Column(String, nullable=False)
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)

    items = relationship("MenuItem", back_populates="category")
