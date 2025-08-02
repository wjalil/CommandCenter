from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Text,Enum 
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid,enum

class OrderStatus(enum.Enum):
    NEW = "New"
    WORKING = "Working"
    COMPLETED = "Completed"


class CustomerOrder(Base):
    __tablename__ = "customer_orders"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    status = Column(Enum(OrderStatus), default=OrderStatus.NEW) 

    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    tenant = relationship("Tenant", back_populates="customer_orders")
    note = Column(Text, nullable=True)


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String, ForeignKey("customer_orders.id"), nullable=False)
    menu_item_id = Column(String, ForeignKey("menu_items.id"), nullable=False)
    quantity = Column(Integer, nullable=False)

    order = relationship("CustomerOrder", back_populates="items")
    menu_item = relationship("MenuItem", back_populates="order_items")