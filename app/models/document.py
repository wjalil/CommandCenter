# models/document.py
from sqlalchemy import Column, String, DateTime,Integer,ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid

class Document(Base):
    __tablename__ = "documents"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String, nullable=False)
    filename = Column(String, nullable=False)  # actual stored filename
    original_filename = Column(String, nullable=False)  # name user uploaded
    tags = Column(String, nullable=True)  # comma-separated string of tags
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    tenant = relationship("Tenant", back_populates="documents")
