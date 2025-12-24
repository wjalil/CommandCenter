from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.schemas.catering import (
    CACFPAgeGroupRead,
    CACFPComponentTypeRead,
    CACFPPortionRuleRead
)
from app.crud.catering import cacfp_rules
from app.db import get_db

router = APIRouter()


@router.get("/age-groups", response_model=List[CACFPAgeGroupRead])
async def list_age_groups(db: AsyncSession = Depends(get_db)):
    """Get all CACFP age groups"""
    return await cacfp_rules.get_all_age_groups(db)


@router.get("/component-types", response_model=List[CACFPComponentTypeRead])
async def list_component_types(db: AsyncSession = Depends(get_db)):
    """Get all CACFP component types"""
    return await cacfp_rules.get_all_component_types(db)


@router.get("/portion-rules", response_model=List[CACFPPortionRuleRead])
async def list_portion_rules(
    age_group_id: int = None,
    meal_type: str = None,
    db: AsyncSession = Depends(get_db)
):
    """Get CACFP portion rules, optionally filtered by age group or meal type"""
    return await cacfp_rules.get_portion_rules(db, age_group_id, meal_type)
