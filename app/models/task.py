from sqlalchemy import Column, String, ForeignKey, Enum, Boolean, Text, DateTime
from sqlalchemy.orm import relationship
from app.models.base import Base
import uuid
import enum
from datetime import datetime


# -- Input Type Enum for prompts
class InputType(str, enum.Enum):
    checkbox = "checkbox"
    text = "text"
    photo = "photo"


# -- A reusable checklist
class TaskTemplate(Base):
    __tablename__ = "task_templates"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)

    auto_assign_label = Column(String, nullable=True)

    items = relationship("TaskItem", back_populates="template")
    tasks = relationship("Task", back_populates="template")


# -- Each step in a checklist (e.g. "Check freezer")
class TaskItem(Base):
    __tablename__ = "task_items"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    prompt = Column(String, nullable=False)
    input_type = Column(Enum(InputType), default=InputType.checkbox)

    template_id = Column(String, ForeignKey("task_templates.id"))
    template = relationship("TaskTemplate", back_populates="items")


# -- Task assigned to a specific shift (e.g. "Monday 7am Shift → Opening Checklist")
class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    shift_id = Column(String, ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True)
    template_id = Column(String, ForeignKey("task_templates.id"))
    is_completed = Column(Boolean, default=False)

    shift = relationship("Shift", back_populates="tasks")
    template = relationship("TaskTemplate", back_populates="tasks")
    submissions = relationship("TaskSubmission", back_populates="task")

class TaskSubmission(Base):
    __tablename__ = "task_submissions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False)
    task_item_id = Column(String, ForeignKey("task_items.id"), nullable=False)
    worker_id = Column(String, ForeignKey("users.id"), nullable=False)
    shift_id = Column(String, ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False)  # 👈 Move this above relationships

    response_text = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    photo_filename = Column(String, nullable=True)  # 📸 New field

    task = relationship("Task", back_populates="submissions")
    task_item = relationship("TaskItem") 
    worker = relationship("User", back_populates="submissions")
    shift = relationship("Shift", back_populates="submissions")  # ✅ must follow the FK
