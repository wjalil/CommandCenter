from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from fastapi.responses import RedirectResponse

from app.schemas.shift import ShiftCreate, ShiftRead
from app.crud import shift as shift_crud
from app.db import get_db
from app.utils.tenant import get_current_tenant_id  # ✅ New import
from app.models.shift import Shift  # ✅ Needed for validation queries

router = APIRouter()

# 🚀 Create a shift
@router.post("/", response_model=ShiftRead)
async def create_shift(
    request: Request,
    shift: ShiftCreate,
    db: AsyncSession = Depends(get_db)
):
    tenant_id = get_current_tenant_id(request)
    return await shift_crud.create_shift(db, shift, tenant_id=tenant_id)


# 📋 List shifts for current tenant
@router.get("/", response_model=List[ShiftRead])
async def list_shifts(request: Request, db: AsyncSession = Depends(get_db)):
    tenant_id = get_current_tenant_id(request)
    return await shift_crud.get_all_shifts(db, tenant_id=tenant_id)


# 🙋 Claim a shift
@router.post("/{shift_id}/claim")
async def claim_shift(
    request: Request,
    shift_id: str,
    user_id: str,
    db: AsyncSession = Depends(get_db)
):
    tenant_id = get_current_tenant_id(request)
    shift = await db.get(Shift, shift_id)

    if not shift or shift.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Unauthorized shift access")

    await shift_crud.claim_shift(db, shift_id, user_id)
    return {"message": "Shift claimed"}


# ✏️ Update shift (safely)
@router.put("/{shift_id}")
async def update_shift(
    request: Request,
    shift_id: str,
    updates: dict,
    db: AsyncSession = Depends(get_db)
):
    tenant_id = get_current_tenant_id(request)
    shift = await db.get(Shift, shift_id)

    if not shift or shift.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Unauthorized shift access")

    await shift_crud.update_shift(db, shift_id, updates)
    return {"message": "Shift updated"}


# ❌ Delete shift
@router.delete("/{shift_id}")
async def delete_shift(request: Request, shift_id: str, db: AsyncSession = Depends(get_db)):
    tenant_id = get_current_tenant_id(request)
    shift = await db.get(Shift, shift_id)

    if not shift or shift.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Unauthorized shift access")

    await shift_crud.delete_shift(db, shift_id)
    return {"message": "Shift deleted"}


# 🙅 Unclaim shift
@router.post("/{shift_id}/unclaim")
async def unclaim_shift(request: Request, shift_id: str, db: AsyncSession = Depends(get_db)):
    tenant_id = get_current_tenant_id(request)
    shift = await db.get(Shift, shift_id)

    if not shift or shift.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Unauthorized shift access")

    await shift_crud.unclaim_shift(db, shift_id)
    return RedirectResponse(url="/admin/shifts", status_code=303)


# ✅ Mark shift complete
@router.post("/{shift_id}/complete")
async def mark_complete(request: Request, shift_id: str, db: AsyncSession = Depends(get_db)):
    tenant_id = get_current_tenant_id(request)
    shift = await db.get(Shift, shift_id)

    if not shift or shift.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Unauthorized shift access")

    await shift_crud.mark_shift_complete(db, shift_id)
    return {"message": "Shift marked as completed"}
