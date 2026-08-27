from sqlalchemy import Column, String, Boolean, Integer, ForeignKey, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid


class CateringClientAccount(Base):
    """Portal login for a catering client (one account per CateringProgram)."""
    __tablename__ = "catering_client_accounts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id = Column(String, ForeignKey("catering_programs.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)

    email = Column(String, nullable=False)
    hashed_password = Column(String, nullable=True)  # null until invite is accepted
    is_active = Column(Boolean, default=True, nullable=False)

    invite_token = Column(String, nullable=True, unique=True)
    invite_token_expires_at = Column(DateTime, nullable=True)
    invite_sent_at = Column(DateTime, nullable=True)

    reset_token = Column(String, nullable=True, unique=True)
    reset_token_expires_at = Column(DateTime, nullable=True)

    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    program = relationship("CateringProgram", back_populates="client_account")
    tenant = relationship("Tenant")

    __table_args__ = (
        UniqueConstraint("program_id", name="uq_client_account_program"),
        Index("idx_client_accounts_tenant", "tenant_id"),
    )
