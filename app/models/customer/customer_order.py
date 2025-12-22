from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Text, Enum, Numeric
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid, enum

class OrderStatus(enum.Enum):
    NEW = "New"
    WORKING = "Working"
    COMPLETED = "Completed"

class PaymentStatus(enum.Enum):
    UNPAID = "Unpaid"
    PAID = "Paid"
    PARTIAL = "Partial"


class CustomerOrder(Base):
    __tablename__ = "customer_orders"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    status = Column(Enum(OrderStatus), default=OrderStatus.NEW)

    # Pricing and payment fields
    total_price = Column(Numeric(10, 2), nullable=False, default=0.00)
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.UNPAID, nullable=False)
    payment_method = Column(String, nullable=True)  # Cash, Card, Account, etc.
    paid_at = Column(DateTime, nullable=True)

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

    # Snapshot pricing and name at time of order
    price_at_time_of_order = Column(Numeric(10, 2), nullable=False)
    item_name = Column(String, nullable=False)

    order = relationship("CustomerOrder", back_populates="items")
    menu_item = relationship("MenuItem", back_populates="order_items")