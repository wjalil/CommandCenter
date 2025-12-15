from sqlalchemy import Column, String, Integer, Float, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid

class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)

    photo_filename = Column(String, nullable=True)  # later: replace with image_url
    qty_available = Column(Integer, default=0)

    menu_id = Column(String, ForeignKey("menus.id"), nullable=False)
    menu = relationship("Menu", back_populates="items")

    category_id = Column(String, ForeignKey("menu_categories.id"), nullable=True)
    category = relationship("MenuCategory", back_populates="items")

    order_items = relationship("OrderItem", back_populates="menu_item", cascade="all, delete-orphan")

