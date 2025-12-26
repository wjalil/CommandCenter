from fastapi import APIRouter, Depends, Request, Query, HTTPException
from typing import Optional
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_ , func , or_, desc, asc
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.sql import over
from app.db import get_db
from app.auth.dependencies import get_current_user  # assumes user has .tenant_id, .role, .name
from app.models.shopping import (
    BusinessLine, Category, Supplier, Item, ShoppingNeed, ShoppingEvent
)
from fastapi.templating import Jinja2Templates
from app.utils.time_windows import parse_since
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


# Batch add multiple items at once
@router.post("/shopping/batch-add")
async def batch_add_items(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Add multiple items to shopping list at once"""
    if not can(user, "cart.toggle_own"):
        raise HTTPException(status_code=403, detail="Forbidden")

    tenant_id = user.tenant_id
    item_ids = payload.get("item_ids", [])
    if not item_ids or not isinstance(item_ids, list):
        raise HTTPException(status_code=400, detail="item_ids array required")

    quantity = max(1, min(int(payload.get("quantity", 1)), 999))
    supplier_id_raw = payload.get("supplier_id")
    supplier_id = _to_int_or_none(str(supplier_id_raw)) if supplier_id_raw else None
    supplier_id = await _validate_supplier_for_tenant(db, tenant_id, supplier_id)

    added_count = 0
    for item_id in item_ids:
        if not item_id:
            continue

        need = await _get_or_create_need(db, tenant_id, str(item_id))
        prev_status = need.status

        need.needed = True
        need.quantity = quantity
        need.supplier_id = supplier_id
        if need.status == "SKIPPED":
            need.status = "NEEDED"

        db.add(
            ShoppingEvent(
                tenant_id=tenant_id,
                item_id=str(item_id),
                from_status=prev_status,
                to_status="NEEDED",
                quantity=quantity,
                actor=user.name,
            )
        )
        added_count += 1

    await db.commit()
    return JSONResponse({"ok": True, "added": added_count})


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

    # Build list of item_ids currently on the list
    item_ids = [n.item_id for n in needs]
    actor_by_item_id = {}

    if item_ids:
        # Window over events to get the most recent NEEDED event per item
        rn = func.row_number().over(
            partition_by=ShoppingEvent.item_id,
            order_by=ShoppingEvent.id.desc()
        ).label("rn")

        subq = (
            select(
                ShoppingEvent.item_id,
                ShoppingEvent.actor,
                rn
            )
            .where(
                ShoppingEvent.tenant_id == tenant_id,
                ShoppingEvent.item_id.in_(item_ids),
                ShoppingEvent.to_status == "NEEDED"
            )
            .subquery("last_needed_event")
        )

        rows = await db.execute(
            select(subq.c.item_id, subq.c.actor).where(subq.c.rn == 1)
        )
        actor_by_item_id = {item_id: actor for item_id, actor in rows.all()}

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
            "actor_by_item_id": actor_by_item_id
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


# ----------------------------
# Item Management (Create/Edit/Delete items in catalog)
# ----------------------------

@router.post("/shopping/items/create")
async def create_item(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a new item in the catalog"""
    if not can(user, "cart.set_status_any"):  # Only admins/managers
        raise HTTPException(status_code=403, detail="Forbidden")

    tenant_id = user.tenant_id
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Item name is required")

    # Check for duplicate
    existing = await db.execute(
        select(Item).where(Item.tenant_id == tenant_id, Item.name == name)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Item with this name already exists")

    # Parse optional fields
    category_id = _to_int_or_none(payload.get("category_id"))
    business_line_id = _to_int_or_none(payload.get("business_line_id"))
    default_supplier_id = _to_int_or_none(payload.get("default_supplier_id"))
    par_level = _to_int_or_none(payload.get("par_level")) or 1
    unit = payload.get("unit", "ea").strip()
    notes = payload.get("notes", "").strip()

    new_item = Item(
        tenant_id=tenant_id,
        name=name,
        category_id=category_id,
        business_line_id=business_line_id,
        default_supplier_id=default_supplier_id,
        par_level=max(1, par_level),
        unit=unit,
        notes=notes,
    )
    db.add(new_item)
    await db.commit()
    await db.refresh(new_item)

    return JSONResponse({"ok": True, "item_id": new_item.id})


@router.post("/shopping/items/{item_id}/update")
async def update_item(
    item_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Update an existing item"""
    if not can(user, "cart.set_status_any"):
        raise HTTPException(status_code=403, detail="Forbidden")

    tenant_id = user.tenant_id
    item = (await db.execute(
        select(Item).where(Item.id == item_id, Item.tenant_id == tenant_id)
    )).scalars().first()

    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Update fields
    if "name" in payload:
        name = payload["name"].strip()
        if name:
            item.name = name
    if "category_id" in payload:
        item.category_id = _to_int_or_none(payload["category_id"])
    if "business_line_id" in payload:
        item.business_line_id = _to_int_or_none(payload["business_line_id"])
    if "default_supplier_id" in payload:
        item.default_supplier_id = _to_int_or_none(payload["default_supplier_id"])
    if "par_level" in payload:
        item.par_level = max(1, _to_int_or_none(payload["par_level"]) or 1)
    if "unit" in payload:
        item.unit = payload["unit"].strip()
    if "notes" in payload:
        item.notes = payload["notes"].strip()

    await db.commit()
    return JSONResponse({"ok": True})


@router.delete("/shopping/items/{item_id}")
async def delete_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete an item from the catalog"""
    if not can(user, "cart.set_status_any"):
        raise HTTPException(status_code=403, detail="Forbidden")

    tenant_id = user.tenant_id
    item = (await db.execute(
        select(Item).where(Item.id == item_id, Item.tenant_id == tenant_id)
    )).scalars().first()

    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    await db.delete(item)
    await db.commit()
    return JSONResponse({"ok": True})


# View Shopping History
# ----------------------------

@router.get("/admin/shopping/purchased")
async def purchased_items_view_join(
    request: Request,
    since: str = Query("7d"),
    q: Optional[str] = Query(None),
    supplier_id: Optional[int] = None,
    bl_id: Optional[int] = None,
    order: str = Query("desc", regex="^(asc|desc)$"),
    limit: int = Query(200, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    tenant_id = user.tenant_id
    since_dt_utc = parse_since(since)
    if getattr(since_dt_utc, "tzinfo", None) is not None:
        since_dt_utc = since_dt_utc.replace(tzinfo=None)

    stmt = (
        select(ShoppingEvent, Item, Supplier, BusinessLine)
        .join(Item, Item.id == ShoppingEvent.item_id)
        .join(Supplier, Supplier.id == Item.default_supplier_id, isouter=True)
        .join(BusinessLine, BusinessLine.id == Item.business_line_id, isouter=True)
        .where(
            ShoppingEvent.tenant_id == tenant_id,
            ShoppingEvent.to_status == "PURCHASED",
            ShoppingEvent.at >= since_dt_utc,
            *( [Item.default_supplier_id == supplier_id] if supplier_id else [] ),
            *( [Item.business_line_id == bl_id] if bl_id else [] ),
            *( [or_(Item.name.ilike(f"%{q.strip()}%"), Item.sku.ilike(f"%{q.strip()}%"))] if q else [] ),
        )
        .order_by(desc(ShoppingEvent.at) if order == "desc" else asc(ShoppingEvent.at))
        .limit(limit)
    )
    res = await db.execute(stmt)
    rows = res.all()  # list of tuples: (ev, item, supplier, bl)

    # Normalize to dicts for the template
    events = [{
        "at": ev.at,
        "quantity": ev.quantity,
        "actor": ev.actor,
        "item_name": item.name if item else "—",
        "supplier_name": supplier.name if supplier else "—",
        "bl_name": bl.name if bl else "—",
    } for (ev, item, supplier, bl) in rows]

    return templates.TemplateResponse(
        "shopping/purchased_list.html",
        {"request": request, "events": events, "since": since, "q": q or "", "supplier_id": supplier_id, "bl_id": bl_id, "order": order},
    )