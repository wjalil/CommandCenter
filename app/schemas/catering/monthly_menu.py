from pydantic import BaseModel
from typing import Optional, List, TYPE_CHECKING
from datetime import date, datetime
from enum import Enum

if TYPE_CHECKING:
    from .menu_day_component import MenuDayComponentRead


class MenuStatus(str, Enum):
    draft = "draft"
    finalized = "finalized"
    sent = "sent"


# ---------- Menu Day (single day's meals) ----------
class MenuDayBase(BaseModel):
    service_date: date
    breakfast_item_id: Optional[str] = None
    breakfast_vegan_item_id: Optional[str] = None
    lunch_item_id: Optional[str] = None
    lunch_vegan_item_id: Optional[str] = None
    snack_item_id: Optional[str] = None
    snack_vegan_item_id: Optional[str] = None
    notes: Optional[str] = None


class MenuDayCreate(MenuDayBase):
    pass


class MenuDayUpdate(MenuDayBase):
    pass


class MenuDayComponentSummary(BaseModel):
    """Summary of a component for display in MenuDayRead"""
    id: str
    component_id: int
    component_name: str
    component_type: str
    meal_slot: str
    is_vegan: bool

    class Config:
        from_attributes = True


class MenuDayRead(MenuDayBase):
    id: str
    monthly_menu_id: str
    components: List[MenuDayComponentSummary] = []

    class Config:
        from_attributes = True


# ---------- Monthly Menu ----------
class MonthlyMenuBase(BaseModel):
    program_id: str
    month: int  # 1-12
    year: int


class MonthlyMenuCreate(MonthlyMenuBase):
    tenant_id: int


class MonthlyMenuUpdate(BaseModel):
    status: Optional[MenuStatus] = None


class MonthlyMenuRead(MonthlyMenuBase):
    id: str
    tenant_id: int
    status: MenuStatus
    finalized_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    menu_days: List[MenuDayRead] = []

    class Config:
        from_attributes = True


# ---------- Menu Day Assignment (for bulk updates) ----------
class MenuDayAssignment(BaseModel):
    """Used for assigning meal items to specific dates"""
    service_date: date
    breakfast_item_id: Optional[str] = None
    breakfast_vegan_item_id: Optional[str] = None
    lunch_item_id: Optional[str] = None
    lunch_vegan_item_id: Optional[str] = None
    snack_item_id: Optional[str] = None
    snack_vegan_item_id: Optional[str] = None
    notes: Optional[str] = None


class BulkMenuDayUpdate(BaseModel):
    """Update multiple menu days at once"""
    monthly_menu_id: str
    menu_days: List[MenuDayAssignment]
