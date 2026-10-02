from datetime import datetime
from uuid import uuid4
import json

from sqlalchemy import Column, String, Integer, Date, DateTime, Numeric, Text, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base


class PayRun(Base):
    """One Friday payroll: every finished, unpaid shift and route through the end
    of a pay week, paid at once. Time entries and delivery routes are stamped with
    the run that paid them, so nothing is paid twice and history is exact."""
    __tablename__ = "payroll_runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    period_start = Column(Date, nullable=False)   # first day of the pay week (e.g. Saturday)
    period_end = Column(Date, nullable=False)     # last day, inclusive = payday (e.g. Friday)
    paid_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    paid_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    payment_method = Column(String, nullable=True)  # Cash, Check, Zelle, Direct deposit…
    notes = Column(Text, nullable=True)
    worker_count = Column(Integer, nullable=False, default=0)
    total_minutes = Column(Integer, nullable=False, default=0)
    total_hourly = Column(Numeric(10, 2), nullable=False, default=0)
    total_route_pay = Column(Numeric(10, 2), nullable=False, default=0)
    total_gross = Column(Numeric(10, 2), nullable=False, default=0)

    paid_by = relationship("User", foreign_keys=[paid_by_id])
    stubs = relationship("PayStub", back_populates="pay_run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_payroll_runs_tenant_period", "tenant_id", "period_end"),
    )


class PayStub(Base):
    """What one worker was paid in one pay run — frozen at the moment of payment,
    shown to the worker, and signed off by them (or disputed) as a receipt."""
    __tablename__ = "pay_stubs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    pay_run_id = Column(String, ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    worker_name = Column(String, nullable=True)  # snapshot
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    minutes = Column(Integer, nullable=False, default=0)
    hourly_gross = Column(Numeric(10, 2), nullable=False, default=0)
    route_pay = Column(Numeric(10, 2), nullable=False, default=0)
    total_gross = Column(Numeric(10, 2), nullable=False, default=0)
    lines_json = Column(Text, nullable=False, default="[]")  # frozen line items, see services/payroll.py
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Worker acknowledgment — the receipt
    status = Column(String, nullable=False, default="issued")  # issued, acknowledged, disputed
    acknowledged_at = Column(DateTime, nullable=True)
    signature_name = Column(String, nullable=True)
    ack_ip = Column(String, nullable=True)
    ack_user_agent = Column(String, nullable=True)
    dispute_note = Column(Text, nullable=True)
    disputed_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_note = Column(Text, nullable=True)

    pay_run = relationship("PayRun", back_populates="stubs")
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("pay_run_id", "user_id", name="uq_pay_stub_run_user"),
        Index("idx_pay_stubs_user", "tenant_id", "user_id"),
    )

    @property
    def lines(self) -> list:
        try:
            return json.loads(self.lines_json or "[]")
        except ValueError:
            return []
