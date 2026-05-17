from sqlalchemy import Column, String, Integer, ForeignKey, Text, Index, Date, DateTime, Numeric
from sqlalchemy.orm import relationship
from app.models.base import Base
from datetime import date, datetime
import uuid

PAYMENT_TYPES = ["insurance", "cash"]
PAYMENT_TYPE_LABELS = {"insurance": "Insurance", "cash": "Cash"}

VALID_STATUSES = [
    "new_arrival",
    "waiting_for_adjuster",
    "waiting_for_parts",
    "disassemble",
    "body_work",
    "paint",
    "assemble",
    "quality_control",
    "complete",
    "ready_for_pickup",
]

STATUS_LABELS = {
    "new_arrival": "New Arrival",
    "waiting_for_adjuster": "Waiting for Adjuster",
    "waiting_for_parts": "Waiting for Parts",
    "disassemble": "Disassemble",
    "body_work": "Body Work",
    "paint": "Paint",
    "assemble": "Assemble",
    "quality_control": "QC / Final Inspection",
    "complete": "Complete",
    "ready_for_pickup": "Ready for Pickup",
}

STATUS_BADGE_COLORS = {
    "new_arrival": "secondary",
    "waiting_for_adjuster": "warning",
    "waiting_for_parts": "warning",
    "disassemble": "info",
    "body_work": "primary",
    "paint": "primary",
    "assemble": "primary",
    "quality_control": "success",
    "complete": "success",
    "ready_for_pickup": "success",
}

# Customer-facing SMS templates. Format keys: year, make, model
STATUS_SMS_MESSAGES = {
    "waiting_for_adjuster": "Update on your {year} {make} {model}: we are waiting on the adjuster. We'll be in touch soon.",
    "waiting_for_parts": "Update on your {year} {make} {model}: we are waiting on parts. We'll notify you when they arrive.",
    "body_work": "Update on your {year} {make} {model}: body work is now underway on your vehicle.",
    "paint": "Update on your {year} {make} {model}: your vehicle is in the paint stage.",
    "quality_control": "Update on your {year} {make} {model}: your vehicle is in final inspection.",
    "complete": "Great news! Your {year} {make} {model} is complete. We'll contact you to arrange pickup.",
    "ready_for_pickup": "Your {year} {make} {model} is ready for pickup. Come in at your convenience!",
}


class RepairOrder(Base):
    __tablename__ = "repair_orders"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_number = Column(String, nullable=False)

    # Vehicle
    vehicle_make = Column(String, nullable=True)
    vehicle_model = Column(String, nullable=True)
    vehicle_year = Column(String, nullable=True)
    vehicle_color = Column(String, nullable=True)
    vehicle_vin = Column(String, nullable=True)
    vehicle_license_plate = Column(String, nullable=True)
    vehicle_mileage = Column(Integer, nullable=True)

    # Customer
    customer_name = Column(String, nullable=False)
    customer_phone = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)

    # Job
    description = Column(Text, nullable=True)
    internal_notes = Column(Text, nullable=True)

    # Payment / financial (admin-only)
    payment_type = Column(String, nullable=True)          # "insurance" | "cash"
    claim_number = Column(String, nullable=True)
    deductible = Column(Numeric(10, 2), nullable=True)
    total_estimate = Column(Numeric(10, 2), nullable=True)
    supplement_1 = Column(Numeric(10, 2), nullable=True)
    supplement_2 = Column(Numeric(10, 2), nullable=True)
    supplement_3 = Column(Numeric(10, 2), nullable=True)
    supplement_4 = Column(Numeric(10, 2), nullable=True)

    # Status
    status = Column(String, nullable=False, default="new_arrival")

    # Assignment
    assigned_tech_id = Column(String, ForeignKey("users.id"), nullable=True)

    # Dates
    intake_date = Column(Date, nullable=False, default=date.today)
    estimated_completion = Column(Date, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)

    tenant = relationship("Tenant", back_populates="repair_orders")
    assigned_tech = relationship(
        "User",
        back_populates="assigned_repairs",
        foreign_keys=[assigned_tech_id],
    )
    payments = relationship(
        "RepairOrderPayment",
        back_populates="repair_order",
        cascade="all, delete-orphan",
        order_by="RepairOrderPayment.date_received",
    )
    photos = relationship(
        "RepairOrderPhoto",
        back_populates="repair_order",
        cascade="all, delete-orphan",
        order_by="RepairOrderPhoto.uploaded_at",
    )
    status_logs = relationship(
        "RepairOrderStatusLog",
        back_populates="repair_order",
        cascade="all, delete-orphan",
        order_by="RepairOrderStatusLog.changed_at",
    )

    __table_args__ = (
        Index("idx_repair_orders_tenant", "tenant_id"),
        Index("idx_repair_orders_status", "tenant_id", "status"),
        Index("idx_repair_orders_intake", "tenant_id", "intake_date"),
    )
