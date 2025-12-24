from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.schemas.catering import (
    CateringProgramCreate,
    CateringProgramUpdate,
    CateringProgramRead
)
from app.crud.catering import program
from app.db import get_db
from app.utils.tenant import get_current_tenant_id

router = APIRouter()


@router.post("/", response_model=CateringProgramRead)
async def create_program(
    request: Request,
    prog: CateringProgramCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new catering program"""
    tenant_id = get_current_tenant_id(request)
    prog.tenant_id = tenant_id
    return await program.create_program(db, prog)


@router.get("/", response_model=List[CateringProgramRead])
async def list_programs(
    request: Request,
    active_only: bool = False,
    db: AsyncSession = Depends(get_db)
):
    """Get all programs for the current tenant"""
    tenant_id = get_current_tenant_id(request)
    return await program.get_programs(db, tenant_id, active_only)


@router.get("/{program_id}", response_model=CateringProgramRead)
async def get_program(
    request: Request,
    program_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific program"""
    tenant_id = get_current_tenant_id(request)
    prog = await program.get_program(db, program_id, tenant_id)
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")
    return prog


@router.put("/{program_id}", response_model=CateringProgramRead)
async def update_program(
    request: Request,
    program_id: str,
    updates: CateringProgramUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a program"""
    tenant_id = get_current_tenant_id(request)
    prog = await program.update_program(db, program_id, tenant_id, updates)
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")
    return prog


@router.delete("/{program_id}")
async def delete_program(
    request: Request,
    program_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a program"""
    tenant_id = get_current_tenant_id(request)
    prog = await program.delete_program(db, program_id, tenant_id)
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")
    return {"message": "Program deleted"}
