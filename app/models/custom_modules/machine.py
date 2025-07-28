from sqlalchemy import Column, String
from app.models.base import Base
import uuid

class Machine(Base):
    __tablename__ = "machines"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, nullable=False)  # e.g. “Union Square Gym”
