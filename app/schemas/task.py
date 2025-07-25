from pydantic import BaseModel
from typing import List, Optional
from enum import Enum
from datetime import datetime


# ---------- Enums ----------
class InputType(str, Enum):
    checkbox = "checkbox"
    text = "text"
    photo = "photo"


# ---------- Task Item ----------
class TaskItemBase(BaseModel):
    prompt: str
    input_type: InputType = InputType.checkbox

class TaskItemCreate(TaskItemBase):
    template_id: Optional[str] = None  # useful for internal use

class TaskItemRead(TaskItemBase):
    id: str

    class Config:
        from_attributes = True


# ---------- Task Template ----------
class TaskTemplateBase(BaseModel):
    title: str
    description: Optional[str] = None

class TaskTemplateCreate(TaskTemplateBase):
    items: Optional[List[TaskItemCreate]] = []

class TaskTemplateRead(TaskTemplateBase):
    id: str
    items: List[TaskItemRead] = []

    class Config:
        from_attributes = True


# ---------- Task (assigned to a shift) ----------
class TaskBase(BaseModel):
    shift_id: str
    template_id: Optional[str] = None

class TaskCreate(TaskBase):
    pass

class TaskRead(BaseModel):
    id: str
    shift_id: str
    is_completed: bool
    template: Optional[TaskTemplateRead] = None

    class Config:
        from_attributes = True


# ---------- Task Submission (worker's response) ----------
class TaskSubmissionBase(BaseModel):
    task_id: str
    task_item_id: str
    worker_id: str
    shift_id: str 
    response_text: Optional[str] = None

class TaskSubmissionCreate(TaskSubmissionBase):
    pass

class TaskSubmissionRead(TaskSubmissionBase):
    id: str
    timestamp: datetime

    class Config:
        from_attributes = True
