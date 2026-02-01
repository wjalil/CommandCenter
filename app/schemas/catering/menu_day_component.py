from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


class MealSlot(str, Enum):
    breakfast = "breakfast"
    lunch = "lunch"
    snack = "snack"


# ---------- Single Component Assignment ----------
class MenuDayComponentBase(BaseModel):
    component_id: int
    meal_slot: MealSlot
    is_vegan: bool = False
    quantity: Optional[Decimal] = None
    notes: Optional[str] = None


class MenuDayComponentCreate(MenuDayComponentBase):
    pass


class MenuDayComponentRead(MenuDayComponentBase):
    id: str
    menu_day_id: str
    component_name: Optional[str] = None
    component_type: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Bulk Assignment Schemas ----------
class MenuDayComponentAssignment(BaseModel):
    """Single component assignment within a bulk operation"""
    component_id: int
    meal_slot: MealSlot
    is_vegan: bool = False
    quantity: Optional[Decimal] = None
    notes: Optional[str] = None


class BulkMenuDayComponentUpdate(BaseModel):
    """Per-day component assignment with service_date"""
    service_date: date
    components: List[MenuDayComponentAssignment]
    replace_existing: bool = True  # If True, removes existing components for this day before adding new ones


class BulkComponentsRequest(BaseModel):
    """Wrapper for bulk component assignment across multiple days"""
    menu_days: List[BulkMenuDayComponentUpdate]
