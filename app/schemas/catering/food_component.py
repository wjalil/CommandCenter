from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from decimal import Decimal


class FoodComponentBase(BaseModel):
    name: str
    component_type_id: int
    default_portion_oz: Decimal
    is_vegan: bool = False
    is_vegetarian: bool = True


class FoodComponentCreate(FoodComponentBase):
    tenant_id: int


class FoodComponentUpdate(BaseModel):
    name: Optional[str] = None
    component_type_id: Optional[int] = None
    default_portion_oz: Optional[Decimal] = None
    is_vegan: Optional[bool] = None
    is_vegetarian: Optional[bool] = None


class FoodComponentRead(FoodComponentBase):
    id: int
    tenant_id: int
    created_at: datetime

    class Config:
        from_attributes = True
