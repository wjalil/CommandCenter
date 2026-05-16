from sqlalchemy import Column, String, Integer, ForeignKey, Text, Index, Date, DateTime
from sqlalchemy.orm import relationship
from app.models.base import Base
from datetime import date, datetime
import uuid

VALID_STATUSES = [
    "intake",
    "diagnosing",
    "waiting_on_parts",
    "parts_received",
    "in_progress",
    "waiting_on_adjuster",
    "adjuster_approved",
    "completed",
    "ready_for_pickup",
]

STATUS_LABELS = {
    "intake": "Intake",
    "diagnosing": "Diagnosing",
    "waiting_on_parts": "Waiting on Parts",
    "parts_received": "Parts Received",
    "in_progress": "In Progress",
    "waiting_on_adjuster": "Waiting on Adjuster",
    "adjuster_approved": "Adjuster Approved",
    "completed": "Completed",
    "ready_for_pickup": "Ready for Pickup",
}

STATUS_BADGE_COLORS = {
    "intake": "secondary",
    "diagnosing": "info",
    "waiting_on_parts": "warning",
    "parts_received": "primary",
    "in_progress": "primary",
    "waiting_on_adjuster": "warning",
    "adjuster_approved": "success",
    "completed": "success",
    "ready_for_pickup": "success",
}

# Customer-facing SMS templates. Format keys: year, make, model
STATUS_SMS_MESSAGES = {
    "waiting_on_parts": "Update on your {year} {make} {model}: we are waiting on parts. We'll notify you when they arrive.",
    "parts_received": "Update on your {year} {make} {model}: parts have arrived and we're getting started.",
    "in_progress": "Update on your {year} {make} {model}: work is now underway on your vehicle.",
    "waiting_on_adjuster": "Update on your {year} {make} {model}: we are waiting on the adjuster. We'll be in touch soon.",
    "adjuster_approved": "Update on your {year} {make} {model}: the adjuster has approved. Work will begin shortly.",
    "completed": "Your {year} {make} {model} is ready! Please contact us to arrange pickup.",
    "ready_for_pickup": "Your {year} {make} {model} is ready for pickup. Come in at your convenience.",
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

    # Status
    status = Column(String, nullable=False, default="intake")

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
