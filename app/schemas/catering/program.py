from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import date, datetime


# ---------- Program Holiday ----------
class ProgramHolidayBase(BaseModel):
    holiday_date: date
    description: Optional[str] = None


class ProgramHolidayCreate(ProgramHolidayBase):
    pass


class ProgramHolidayRead(ProgramHolidayBase):
    id: str
    program_id: str

    class Config:
        from_attributes = True


# ---------- Catering Program ----------
class CateringProgramBase(BaseModel):
    name: str
    client_name: str
    client_email: Optional[EmailStr] = None
    client_phone: Optional[str] = None
    address: Optional[str] = None
    age_group_id: int
    total_children: int
    vegan_count: int = 0
    invoice_prefix: str  # e.g., "BC", "LC"
    service_days: List[str]  # ["Monday", "Tuesday", ...]
    meal_types_required: List[str]  # ["Breakfast", "Lunch", "Snack"]
    start_date: date
    end_date: Optional[date] = None
    is_active: bool = True


class CateringProgramCreate(CateringProgramBase):
    tenant_id: int
    holidays: List[ProgramHolidayCreate] = []


class CateringProgramUpdate(BaseModel):
    name: Optional[str] = None
    client_name: Optional[str] = None
    client_email: Optional[EmailStr] = None
    client_phone: Optional[str] = None
    address: Optional[str] = None
    age_group_id: Optional[int] = None
    total_children: Optional[int] = None
    vegan_count: Optional[int] = None
    invoice_prefix: Optional[str] = None
    service_days: Optional[List[str]] = None
    meal_types_required: Optional[List[str]] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None
    holidays: Optional[List[ProgramHolidayCreate]] = None


class CateringProgramRead(CateringProgramBase):
    id: str
    tenant_id: int
    last_invoice_number: int
    created_at: datetime
    updated_at: datetime
    holidays: List[ProgramHolidayRead] = []

    class Config:
        from_attributes = True
