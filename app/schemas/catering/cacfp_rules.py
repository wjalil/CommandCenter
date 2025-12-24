from pydantic import BaseModel
from typing import Optional
from decimal import Decimal


# ---------- CACFP Age Group ----------
class CACFPAgeGroupBase(BaseModel):
    name: str
    age_min_months: int
    age_max_months: Optional[int] = None
    sort_order: int


class CACFPAgeGroupRead(CACFPAgeGroupBase):
    id: int

    class Config:
        from_attributes = True


# ---------- CACFP Component Type ----------
class CACFPComponentTypeBase(BaseModel):
    name: str
    description: Optional[str] = None
    sort_order: int


class CACFPComponentTypeRead(CACFPComponentTypeBase):
    id: int

    class Config:
        from_attributes = True


# ---------- CACFP Portion Rule ----------
class CACFPPortionRuleBase(BaseModel):
    age_group_id: int
    component_type_id: int
    meal_type: str  # Breakfast, Lunch, Snack
    min_portion_oz: Decimal
    max_portion_oz: Optional[Decimal] = None
    notes: Optional[str] = None


class CACFPPortionRuleRead(CACFPPortionRuleBase):
    id: int

    class Config:
        from_attributes = True
