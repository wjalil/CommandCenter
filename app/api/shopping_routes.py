from fastapi import APIRouter, Depends, Request, Query
from typing import Optional
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.db import get_db
from app.auth.dependencies import get_current_user  # assumes user has .tenant_id and .name
from app.models.shopping import (
    BusinessLine, Category, Supplier, Item, ShoppingNeed, ShoppingEvent
)

router = APIRouter()
# If you already use a global templates object, import it; otherwise:
from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="app/templates")

def _to_int_or_none(val: Optional[str]) -> Optional[int]:
    if val is None:
        return None
    val = val.strip()
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None




# ---------- helpers ----------
async def _get_or_create_need(db: AsyncSession, tenant_id: int, item_id: str) -> ShoppingNeed:
    q = await db.execute(select(ShoppingNeed).where(
        ShoppingNeed.tenant_id==tenant_id, ShoppingNeed.item_id==item_id
    ))
    need = q.scalars().first()
    if not need:
        need = ShoppingNeed(tenant_id=tenant_id, item_id=item_id, needed=False, status="NEEDED", quantity=1)
        db.add(need)
        await db.flush()
    return need

# ---------- Admin: create list ----------
@router.get("/admin/shopping/items")
async def admin_items(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    tenant_id = user.tenant_id

    items = (await db.execute(
        select(Item)
        .options(selectinload(Item.default_supplier),
                 selectinload(Item.category),
                 selectinload(Item.business_line))
        .where(Item.tenant_id==tenant_id)
        .order_by(Item.name)
    )).scalars().all()

    suppliers = (await db.execute(
        select(Supplier).where(Supplier.tenant_id==tenant_id).order_by(Supplier.name)
    )).scalars().all()

    # dynamic filters (optional UI chips)
    business_lines = (await db.execute(
        select(BusinessLine).where(BusinessLine.tenant_id==tenant_id).order_by(BusinessLine.name)
    )).scalars().all()
    categories = (await db.execute(
        select(Category).where(Category.tenant_id==tenant_id).order_by(Category.name)
    )).scalars().all()

    return templates.TemplateResponse("shopping/admin_items.html", {
        "request": request,
        "items": items,
        "suppliers": suppliers,
        "business_lines": business_lines,
        "categories": categories,
    })

@router.post("/admin/shopping/toggle")
async def admin_toggle_need(payload: dict, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    tenant_id = user.tenant_id
    item_id = payload.get("item_id")
    needed = bool(payload.get("needed", True))
    quantity = int(payload.get("quantity") or 1)
    supplier_id = payload.get("supplier_id")
    notes = payload.get("notes")

    need = await _get_or_create_need(db, tenant_id, item_id)
    prev_status = need.status

    need.needed = needed
    need.quantity = quantity
    need.supplier_id = supplier_id
    if notes is not None:
        need.notes = notes
    # when turning on, ensure status is NEEDED
    if needed and need.status == "SKIPPED":
        need.status = "NEEDED"

    db.add(ShoppingEvent(
        tenant_id=tenant_id, item_id=item_id,
        from_status=None if needed else prev_status,
        to_status="NEEDED" if needed else "SKIPPED",
        quantity=quantity, actor=user.name, note=notes
    ))
    await db.commit()
    return JSONResponse({"ok": True})

# ---------- Runner: work the list ----------
@router.get("/admin/shopping/view")
async def shopping_view(
    request: Request,
    supplier_id: Optional[str] = Query(None),         # accept raw strings
    business_line_id: Optional[str] = Query(None),    # accept raw strings
    q: Optional[str] = Query(None),                   # optional text search
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    tenant_id = user.tenant_id

    # safely coerce once
    supplier_id_i = _to_int_or_none(supplier_id)
    business_line_id_i = _to_int_or_none(business_line_id)

    stmt = (
        select(ShoppingNeed)
        .options(
            selectinload(ShoppingNeed.item).selectinload(Item.default_supplier),
            selectinload(ShoppingNeed.item).selectinload(Item.category),
            selectinload(ShoppingNeed.item).selectinload(Item.business_line),
            selectinload(ShoppingNeed.supplier),
        )
        .where(ShoppingNeed.tenant_id == tenant_id, ShoppingNeed.needed == True)
        .order_by(ShoppingNeed.item_id)
    )

    if business_line_id_i is not None:
        stmt = stmt.join(ShoppingNeed.item).where(Item.business_line_id == business_line_id_i)

    if supplier_id_i is not None:
        stmt = stmt.where(ShoppingNeed.supplier_id == supplier_id_i)

    if q:
        like = f"%{q.strip()}%"
        # search on item name / sku / notes as examples—tailor to your schema
        stmt = stmt.join(ShoppingNeed.item).where(
            (Item.name.ilike(like)) | (Item.sku.ilike(like)) | (ShoppingNeed.notes.ilike(like))
        )

    needs = (await db.execute(stmt)).scalars().all()

    suppliers = (
        await db.execute(
            select(Supplier).where(Supplier.tenant_id == tenant_id).order_by(Supplier.name)
        )
    ).scalars().all()

    business_lines = (
        await db.execute(
            select(BusinessLine).where(BusinessLine.tenant_id == tenant_id).order_by(BusinessLine.name)
        )
    ).scalars().all()

    return templates.TemplateResponse(
        "shopping/shopping_view.html",
        {
            "request": request,
            "needs": needs,
            "suppliers": suppliers,
            "business_lines": business_lines,
            "active_supplier_id": supplier_id_i,
            "active_business_line_id": business_line_id_i,
            "q": q or "",
        },
    )

@router.post("/shopping/status")
async def shopping_set_status(payload: dict, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    tenant_id = user.tenant_id
    item_id = payload.get("item_id")
    to_status = payload.get("status")
    quantity = payload.get("quantity")
    notes = payload.get("notes")

    q = await db.execute(select(ShoppingNeed).where(
        ShoppingNeed.tenant_id==tenant_id, ShoppingNeed.item_id==item_id
    ))
    need = q.scalars().first()
    if not need:
        return JSONResponse({"ok": False, "error": "Need not found"}, status_code=404)

    prev_status = need.status
    need.status = to_status or prev_status
    if quantity is not None:
        need.quantity = int(quantity)
    if to_status == "PURCHASED":
        need.needed = False

    db.add(ShoppingEvent(
        tenant_id=tenant_id, item_id=item_id,
        from_status=prev_status, to_status=need.status,
        quantity=need.quantity, actor=user.name, note=notes
    ))
    await db.commit()
    return JSONResponse({"ok": True})
