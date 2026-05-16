from sqlalchemy import Column, String, Integer, ForeignKey, Date, DateTime, Numeric, Text
from sqlalchemy.orm import relationship
from app.models.base import Base
from datetime import datetime, date
import uuid

PAYMENT_METHODS = [
    "insurance_check",
    "deductible",
    "cash",
    "zelle",
    "paypal",
    "credit_card",
    "snap_finance",
    "other",
]

PAYMENT_METHOD_LABELS = {
    "insurance_check": "Insurance Check",
    "deductible": "Deductible",
    "cash": "Cash",
    "zelle": "Zelle",
    "paypal": "PayPal",
    "credit_card": "Credit Card",
    "snap_finance": "Snap Finance",
    "other": "Other",
}


class RepairOrderPayment(Base):
    __tablename__ = "repair_order_payments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    repair_order_id = Column(String, ForeignKey("repair_orders.id", ondelete="CASCADE"), nullable=False)
    payment_method = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    date_received = Column(Date, nullable=False, default=date.today)
    notes = Column(Text, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    repair_order = relationship("RepairOrder", back_populates="payments")
