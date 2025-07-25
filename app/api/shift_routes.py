from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.schemas.shift import ShiftCreate, ShiftRead
from app.crud import shift as shift_crud
from app.db import get_db

router = APIRouter()

@router.post("/", response_model=ShiftRead)
async def create_shift(shift: ShiftCreate, db: AsyncSession = Depends(get_db)):
    return await shift_crud.create_shift(db, shift)

@router.get("/", response_model=List[ShiftRead])
async def list_shifts(db: AsyncSession = Depends(get_db)):
    return await shift_crud.get_all_shifts(db)

@router.post("/{shift_id}/claim")
async def claim_shift(shift_id: str, user_id: str, db: AsyncSession = Depends(get_db)):
    await shift_crud.claim_shift(db, shift_id, user_id)
    return {"message": "Shift claimed"}

@router.put("/{shift_id}")
async def update_shift(shift_id: str, updates: dict, db: AsyncSession = Depends(get_db)):
    await shift_crud.update_shift(db, shift_id, updates)
    return {"message": "Shift updated"}

@router.delete("/{shift_id}")
async def delete_shift(shift_id: str, db: AsyncSession = Depends(get_db)):
    await shift_crud.delete_shift(db, shift_id)
    return {"message": "Shift deleted"}

@router.post("/{shift_id}/unclaim")
async def unclaim_shift(shift_id: str, db: AsyncSession = Depends(get_db)):
    await shift_crud.unclaim_shift(db, shift_id)
    return {"message": "Shift unclaimed"}

@router.post("/{shift_id}/complete")
async def mark_complete(shift_id: str, db: AsyncSession = Depends(get_db)):
    await shift_crud.mark_shift_complete(db, shift_id)
    return {"message": "Shift marked as completed"}
