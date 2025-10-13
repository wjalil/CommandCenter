from fastapi import APIRouter, Depends, Request, Query, HTTPException
from typing import Optional
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from app.db import get_db
from app.auth.dependencies import get_current_user  # assumes user has .tenant_id, .role, .name
from app.models.shopping import (
    BusinessLine, Category, Supplier, Item, ShoppingNeed, ShoppingEvent
)
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ----------------------------
# Role capabilities (simple)
# ----------------------------
def can(user, capability: str) -> bool:
    role = (getattr(user, "role", "") or "").lower()
    table = {
        "worker":  {"cart.view", "cart.toggle_own", "cart.view_list"},
        "manager": {"cart.view", "cart.toggle_own", "cart.view_list", "cart.set_status_any"},
        "admin":   {"cart.view", "cart.toggle_own", "cart.view_list", "cart.set_status_any"},
    }
    return capability in table.get(role, set())


# ----------------------------
# Utils
# ----------------------------
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


async def _get_or_create_need(db: AsyncSession, tenant_id: int, item_id: str) -> ShoppingNeed:
    q = await db.execute(
        select(ShoppingNeed).where(
            and_(
                ShoppingNeed.tenant_id == tenant_id,
                ShoppingNeed.item_id == item_id
            )
        )
    )
    need = q.scalars().first()
    if not need:
        need = ShoppingNeed(
            tenant_id=tenant_id,
            item_id=item_id,
            needed=False,
            status="NEEDED",
            quantity=1,
        )
        db.add(need)
        await db.flush()
    return need


async def _validate_supplier_for_tenant(db: AsyncSession, tenant_id: int, supplier_id: Optional[int]) -> Optional[int]:
    if supplier_id is None:
        return None
    q = await db.execute(
        select(Supplier).where(and_(Supplier.id == supplier_id, Supplier.tenant_id == tenant_id))
    )
    if not q.scalars().first():
        raise HTTPException(status_code=400, detail="Invalid supplier")
    return supplier_id


# ----------------------------
# Shared: Item catalog (toggle “Need”)
# (workers and admins share the view)
# ----------------------------
@router.get("/shopping/items")
async def items_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    if not can(user, "cart.view"):
        raise HTTPException(status_code=403, detail="Forbidden")

    tenant_id = user.tenant_id

    items = (
        await db.execute(
            select(Item)
            .options(
                selectinload(Item.default_supplier),
                selectinload(Item.category),
                selectinload(Item.business_line),
            )
            .where(Item.tenant_id == tenant_id)
            .order_by(Item.name)
        )
    ).scalars().all()

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

    categories = (
        await db.execute(
            select(Category).where(Category.tenant_id == tenant_id).order_by(Category.name)
        )
    ).scalars().all()

    return templates.TemplateResponse(
        "shopping/admin_items.html",  # reuse your existing template
        {
            "request": request,
            "items": items,
            "suppliers": suppliers,
            "business_lines": business_lines,
            "categories": categories,
            "user": user,  # handy for role-based affordances in the template
        },
    )


# Alias to keep old links working (optional)
@router.get("/admin/shopping/items")
async def admin_items_alias(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return await items_page(request, db, user)


# Toggle “needed” for an item (workers can do this for the tenant list)
@router.post("/shopping/toggle")
async def toggle_need(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    if not can(user, "cart.toggle_own"):
        raise HTTPException(status_code=403, detail="Forbidden")

    tenant_id = user.tenant_id
    item_id = payload.get("item_id")
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id required")

    needed = bool(payload.get("needed", True))
    # clamp quantity
    try:
        quantity = int(payload.get("quantity") or 1)
    except Exception:
        quantity = 1
    quantity = max(1, min(quantity, 999))

    supplier_id_raw = payload.get("supplier_id")
    supplier_id = _to_int_or_none(str(supplier_id_raw)) if supplier_id_raw is not None else None
    supplier_id = await _validate_supplier_for_tenant(db, tenant_id, supplier_id)

    notes = payload.get("notes")
    if notes is not None:
        notes = (str(notes) or "")[:500]  # prevent unbounded notes

    need = await _get_or_create_need(db, tenant_id, item_id)
    prev_status = need.status

    need.needed = needed
    need.quantity = quantity
    need.supplier_id = supplier_id
    if notes is not None:
        need.notes = notes
    # Simple status rule: if marking not-needed, mark SKIPPED; if marking needed, ensure NEEDED
    if needed:
        if need.status == "SKIPPED":
            need.status = "NEEDED"
    else:
        need.status = "SKIPPED"

    db.add(
        ShoppingEvent(
            tenant_id=tenant_id,
            item_id=item_id,
            from_status=prev_status if not needed else None,
            to_status="NEEDED" if needed else "SKIPPED",
            quantity=quantity,
            actor=user.name,
            note=notes,
        )
    )
    await db.commit()
    return JSONResponse({"ok": True})


# Keep the old admin toggle path as an alias (optional)
@router.post("/admin/shopping/toggle")
async def admin_toggle_need_alias(payload: dict, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return await toggle_need(payload, db, user)


# ----------------------------
# Shared: “Work the list” view
# ----------------------------
@router.get("/shopping/view")
async def shopping_view(
    request: Request,
    supplier_id: Optional[str] = Query(None),
    business_line_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    if not can(user, "cart.view_list"):
        raise HTTPException(status_code=403, detail="Forbidden")

    tenant_id = user.tenant_id
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
        stmt = stmt.join(ShoppingNeed.item).where(
            (Item.name.ilike(like)) | (Item.sku.ilike(like)) | (ShoppingNeed.notes.ilike(like))
        )

    needs = (await db.execute(stmt)).scalars().all()

    suppliers = (
        await db.execute(select(Supplier).where(Supplier.tenant_id == tenant_id).order_by(Supplier.name))
    ).scalars().all()

    business_lines = (
        await db.execute(select(BusinessLine).where(BusinessLine.tenant_id == tenant_id).order_by(BusinessLine.name))
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
            "user": user,  # for minor UI affordances if needed
        },
    )


# Back-compat alias (optional)
@router.get("/admin/shopping/view")
async def shopping_view_alias(
    request: Request,
    supplier_id: Optional[str] = Query(None),
    business_line_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await shopping_view(request, supplier_id, business_line_id, q, db, user)


# ----------------------------
# Status transitions (purchase, received, etc.)
# Workers can NOT mark as PURCHASED/RECEIVED; managers/admins can.
# ----------------------------
@router.post("/shopping/status")
async def shopping_set_status(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    tenant_id = user.tenant_id
    item_id = payload.get("item_id")
    to_status_raw = payload.get("status")
    if not item_id or not to_status_raw:
        raise HTTPException(status_code=400, detail="item_id and status are required")

    # Normalize status to upper
    to_status = str(to_status_raw).upper().strip()

    # Role-based allowed statuses
    worker_allowed = {"NEEDED", "SKIPPED"}  # workers can only mark needed or skip
    privileged_allowed = {"NEEDED", "SKIPPED", "PURCHASED", "RECEIVED"}  # managers/admins

    if can(user, "cart.set_status_any"):
        allowed = privileged_allowed
    else:
        allowed = worker_allowed

    if to_status not in allowed:
        raise HTTPException(status_code=403, detail=f"Status '{to_status}' not allowed")

    q = await db.execute(
        select(ShoppingNeed).where(
            and_(ShoppingNeed.tenant_id == tenant_id, ShoppingNeed.item_id == item_id)
        )
    )
    need = q.scalars().first()
    if not need:
        return JSONResponse({"ok": False, "error": "Need not found"}, status_code=404)

    prev_status = need.status

    # optional: clamp quantity if provided
    quantity = payload.get("quantity")
    if quantity is not None:
        try:
            quantity = int(quantity)
        except Exception:
            quantity = need.quantity or 1
        need.quantity = max(1, min(quantity, 999))

    notes = payload.get("notes")
    if notes is not None:
        need.notes = (str(notes) or "")[:500]

    need.status = to_status
    if to_status == "PURCHASED":
        need.needed = False
    elif to_status == "NEEDED":
        need.needed = True
    elif to_status == "SKIPPED":
        need.needed = False

    db.add(
        ShoppingEvent(
            tenant_id=tenant_id,
            item_id=item_id,
            from_status=prev_status,
            to_status=need.status,
            quantity=need.quantity,
            actor=user.name,
            note=notes,
        )
    )
    await db.commit()
    return JSONResponse({"ok": True})
