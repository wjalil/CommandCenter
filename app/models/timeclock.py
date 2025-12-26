from datetime import datetime
from sqlalchemy import (
    Column, String, DateTime, Integer, Boolean, ForeignKey,
    Enum, Index, Numeric, CheckConstraint, func
)
from sqlalchemy.orm import relationship
import enum
from app.db import Base


class TimeStatus(str, enum.Enum):
    OPEN = "OPEN"         # clocked in, no clock_out yet
    CLOSED = "CLOSED"     # clocked out
    APPROVED = "APPROVED" # admin reviewed (optional step)
    PAID = "PAID"         # payroll processed


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id = Column(String, primary_key=True)
    tenant_id = Column(Integer, nullable=False, index=True)

    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    shift_id = Column(String, ForeignKey("shifts.id"), nullable=True, index=True)

    # Always store UTC datetimes (convert on display if needed)
    clock_in = Column(DateTime(timezone=False), nullable=False, default=func.now())
    clock_out = Column(DateTime(timezone=False), nullable=True)

    status = Column(Enum(TimeStatus), nullable=False, default=TimeStatus.OPEN)
    notes = Column(String, nullable=True)

    # optional audit/context
    clock_in_source = Column(String, nullable=True)
    clock_out_source = Column(String, nullable=True)
    clock_in_ip = Column(String, nullable=True)
    clock_out_ip = Column(String, nullable=True)

    # snapshot at close
    duration_minutes = Column(Integer, nullable=True)
    hourly_rate = Column(Numeric(10, 2), nullable=True)
    gross_pay = Column(Numeric(10, 2), nullable=True)

    is_seed = Column(Boolean, default=False)

    # Audit trail for edits/manual entries
    created_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    edited_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    edited_at = Column(DateTime, nullable=True)
    is_manual = Column(Boolean, default=False, nullable=False)
    edit_reason = Column(String, nullable=True)

    user = relationship("User", foreign_keys=[user_id], backref="time_entries")
    shift = relationship("Shift", backref="time_entries")
    created_by = relationship("User", foreign_keys=[created_by_id])
    edited_by = relationship("User", foreign_keys=[edited_by_id])

    __table_args__ = (
        CheckConstraint(
            'duration_minutes IS NULL OR duration_minutes >= 0',
            name='ck_time_entries_duration_nonneg'
        ),
        CheckConstraint(
            'gross_pay IS NULL OR gross_pay >= 0',
            name='ck_time_entries_gross_nonneg'
        ),
    )


# Helpful index; partial unique index enforced in Alembic migration
Index("ix_time_entries_open_unique", TimeEntry.user_id, TimeEntry.tenant_id, TimeEntry.status)
