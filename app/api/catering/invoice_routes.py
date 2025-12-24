from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.schemas.catering import (
    CateringInvoiceCreate,
    CateringInvoiceUpdate,
    CateringInvoiceRead
)
from app.crud.catering import invoice
from app.db import get_db
from app.utils.tenant import get_current_tenant_id

router = APIRouter()


@router.post("/", response_model=CateringInvoiceRead)
async def create_invoice(
    request: Request,
    inv: CateringInvoiceCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new catering invoice"""
    tenant_id = get_current_tenant_id(request)
    inv.tenant_id = tenant_id
    return await invoice.create_invoice(db, inv)


@router.get("/", response_model=List[CateringInvoiceRead])
async def list_invoices(
    request: Request,
    program_id: str = None,
    db: AsyncSession = Depends(get_db)
):
    """Get all invoices for the current tenant"""
    tenant_id = get_current_tenant_id(request)
    return await invoice.get_invoices(db, tenant_id, program_id)


@router.get("/{invoice_id}", response_model=CateringInvoiceRead)
async def get_invoice(
    request: Request,
    invoice_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific invoice"""
    tenant_id = get_current_tenant_id(request)
    inv = await invoice.get_invoice(db, invoice_id, tenant_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@router.put("/{invoice_id}", response_model=CateringInvoiceRead)
async def update_invoice(
    request: Request,
    invoice_id: str,
    updates: CateringInvoiceUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update an invoice"""
    tenant_id = get_current_tenant_id(request)
    inv = await invoice.update_invoice(db, invoice_id, tenant_id, updates)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@router.delete("/{invoice_id}")
async def delete_invoice(
    request: Request,
    invoice_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete an invoice"""
    tenant_id = get_current_tenant_id(request)
    inv = await invoice.delete_invoice(db, invoice_id, tenant_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"message": "Invoice deleted"}
