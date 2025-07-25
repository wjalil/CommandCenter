from pydantic import BaseModel

class TaskSubmissionBase(BaseModel):
    value: str
    shift_id: str
    worker_id: str
    task_item_id: str

class TaskSubmissionCreate(TaskSubmissionBase):
    pass

class TaskSubmissionRead(TaskSubmissionBase):
    id: str

    class Config:
        from_attributes = True
