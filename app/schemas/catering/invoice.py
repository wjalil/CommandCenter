from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime
from enum import Enum


class InvoiceStatus(str, Enum):
    draft = "draft"
    finalized = "finalized"
    sent = "sent"
    paid = "paid"


class CateringInvoiceBase(BaseModel):
    program_id: str
    service_date: date
    regular_meal_count: int
    vegan_meal_count: int = 0


class CateringInvoiceCreate(CateringInvoiceBase):
    tenant_id: int
    monthly_menu_id: Optional[str] = None
    menu_day_id: Optional[str] = None


class CateringInvoiceUpdate(BaseModel):
    regular_meal_count: Optional[int] = None
    vegan_meal_count: Optional[int] = None
    status: Optional[InvoiceStatus] = None
    pdf_filename: Optional[str] = None


class CateringInvoiceRead(CateringInvoiceBase):
    id: str
    invoice_number: str
    tenant_id: int
    monthly_menu_id: Optional[str] = None
    menu_day_id: Optional[str] = None
    status: InvoiceStatus
    pdf_filename: Optional[str] = None
    created_at: datetime
    sent_at: Optional[datetime] = None

    class Config:
        from_attributes = True
