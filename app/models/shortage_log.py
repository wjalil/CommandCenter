from sqlalchemy import Column, String, DateTime, Boolean
from app.models.base import Base
import uuid
from datetime import datetime

class ShortageLog(Base):
    __tablename__ = "shortage_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    note = Column(String, nullable=False)
    is_resolved = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow)