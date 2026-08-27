from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Text, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid

REQUEST_TYPES = ("count_change", "menu_feedback", "general")
REQUEST_STATUSES = ("open", "acknowledged", "resolved")


class ClientPortalRequest(Base):
    """A request/feedback item submitted by a catering client through the portal."""
    __tablename__ = "client_portal_requests"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id = Column(String, ForeignKey("catering_programs.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    client_account_id = Column(String, ForeignKey("catering_client_accounts.id"), nullable=True)

    request_type = Column(String, nullable=False, default="general")  # count_change, menu_feedback, general
    message = Column(Text, nullable=False)
    proposed_counts = Column(Text, nullable=True)  # JSON blob, e.g. {"lunch_count": 24}

    status = Column(String, default="open", nullable=False)  # open, acknowledged, resolved
    staff_reply = Column(Text, nullable=True)
    resolved_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    program = relationship("CateringProgram", back_populates="portal_requests")
    tenant = relationship("Tenant")
    client_account = relationship("CateringClientAccount")
    resolved_by = relationship("User")

    __table_args__ = (
        Index("idx_portal_requests_tenant", "tenant_id"),
        Index("idx_portal_requests_program", "program_id"),
        Index("idx_portal_requests_status", "tenant_id", "status"),
    )
