from sqlalchemy import Column, String, Boolean
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    pin_code = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "admin", "worker"
    worker_type = Column(String, nullable=True) 

    is_active = Column(Boolean, default=True)

    business_id = Column(String, nullable=True)  # just store it raw for now

    shifts = relationship("Shift", back_populates="worker")
    submissions = relationship("TaskSubmission", back_populates="worker")
