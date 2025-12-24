from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum


class MealType(str, Enum):
    breakfast = "Breakfast"
    lunch = "Lunch"
    snack = "Snack"


# ---------- Meal Component (food items within a meal) ----------
class MealComponentBase(BaseModel):
    food_component_id: int
    portion_oz: Decimal


class MealComponentCreate(MealComponentBase):
    pass


class MealComponentRead(MealComponentBase):
    id: str
    meal_item_id: str

    class Config:
        from_attributes = True


# ---------- Meal Item ----------
class CateringMealItemBase(BaseModel):
    name: str
    description: Optional[str] = None
    meal_type: MealType
    is_vegan: bool = False
    is_vegetarian: bool = False
    photo_filename: Optional[str] = None


class CateringMealItemCreate(CateringMealItemBase):
    tenant_id: int
    components: List[MealComponentCreate] = []


class CateringMealItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    meal_type: Optional[MealType] = None
    is_vegan: Optional[bool] = None
    is_vegetarian: Optional[bool] = None
    photo_filename: Optional[str] = None
    components: Optional[List[MealComponentCreate]] = None


class CateringMealItemRead(CateringMealItemBase):
    id: str
    tenant_id: int
    created_at: datetime
    updated_at: datetime
    components: List[MealComponentRead] = []

    class Config:
        from_attributes = True
