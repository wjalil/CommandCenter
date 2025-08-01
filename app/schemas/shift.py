from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class ShiftBase(BaseModel):
    label: str
    start_time: datetime
    end_time: datetime
    is_recurring: Optional[bool] = False  # ✅ Add here so it's supported in ShiftCreate
    shift_type: Optional[str] = None 

class ShiftCreate(ShiftBase):
    tenant_id: str

class ShiftRead(ShiftBase):  # ✅ Inherit from ShiftBase to avoid repetition
    id: str
    assigned_worker_id: Optional[str] = None
    is_filled: Optional[bool] = False
    is_completed: Optional[bool] = False

    class Config:
        orm_mode = True
