from fastapi import APIRouter, Depends, Request, Form, Body, File, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.menu.menu_item import MenuItem
from app.models.menu.menu import Menu
from app.models.menu.menu_category import MenuCategory  # NEW (safe even if not used yet)
from app.core.constants import UPLOAD_PATHS

from app.utils.spaces import put_public_object


import os
import uuid
from typing import Optional

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = UPLOAD_PATHS["menu_items_photos"]

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _ensure_upload_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


async def _save_uploaded_photo(photo: UploadFile, tenant_id: int) -> str:
    """
    Saves photo to disk under a tenant-specific directory.
    NOTE: This is a temporary strategy until DO Spaces is implemented.
    """
    ext = os.path.splitext(photo.filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        raise ValueError("Invalid image type. Allowed: jpg, jpeg, png, webp")

    # tenant-scoped folder keeps things clean even before Spaces
    tenant_dir = os.path.join(UPLOAD_DIR, str(tenant_id))
    _ensure_upload_dir(tenant_dir)

    filename = f"{uuid.uuid4()}{ext}"
    path = os.path.join(tenant_dir, filename)

    # Write bytes
    content = await photo.read()
    with open(path, "wb") as f:
        f.write(content)

    # Store relative path from UPLOAD_DIR, or just filename—depends on how you serve static.
    # This stores tenant_id/filename which is more robust.
    return f"{tenant_id}/{filename}"


async def _get_menu_for_tenant(db: AsyncSession, menu_id: str, tenant_id: int) -> Optional[Menu]:
    res = await db.execute(select(Menu).where(Menu.id == menu_id, Menu.tenant_id == tenant_id))
    return res.scalar_one_or_none()


async def _get_item_for_tenant(db: AsyncSession, item_id: str, tenant_id: int) -> Optional[MenuItem]:
    """
    Loads a MenuItem by id, then validates tenant ownership via the parent Menu.
    (MenuItem has no tenant_id column in your schema.)
    """
    res = await db.execute(select(MenuItem).where(MenuItem.id == item_id))
    item = res.scalar_one_or_none()
    if not item:
        return None

    menu = await _get_menu_for_tenant(db, item.menu_id, tenant_id)
    if not menu:
        return None

    return item


# ----- Render Menu Builder Page
@router.get("/admin/menu-items/create")
async def menu_builder_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    # Show menus for this tenant
    result = await db.execute(select(Menu).where(Menu.tenant_id == user.tenant_id).order_by(Menu.name.asc()))
    menus = result.scalars().all()

    # Optional: if template supports it later, show categories for a selected menu_id
    selected_menu_id = request.query_params.get("menu_id")
    categories = []
    if selected_menu_id:
        menu = await _get_menu_for_tenant(db, selected_menu_id, user.tenant_id)
        if menu:
            cat_res = await db.execute(
                select(MenuCategory)
                .where(MenuCategory.menu_id == selected_menu_id, MenuCategory.tenant_id == user.tenant_id)
                .order_by(MenuCategory.display_order.asc(), MenuCategory.name.asc())
            )
            categories = cat_res.scalars().all()

    return templates.TemplateResponse(
        "menus/menu_builder.html",
        {"request": request, "menus": menus, "categories": categories, "user": user},
    )


# ----- Create Menu Item (single)
@router.post("/admin/menu-items/create")
async def create_menu_item(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    price: float = Form(...),
    quantity: int = Form(...),
    menu_id: str = Form(...),
    category_id: Optional[str] = Form(None),
    photo: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    # Validate menu ownership
    res_menu = await db.execute(
        select(Menu).where(Menu.id == menu_id, Menu.tenant_id == user.tenant_id)
    )
    menu = res_menu.scalars().first()
    if not menu:
        return RedirectResponse(url="/admin/menus?error=Invalid+menu", status_code=303)

    # Optional: validate category belongs to this menu+tenant
    if category_id:
        res_cat = await db.execute(
            select(MenuCategory).where(
                MenuCategory.id == category_id,
                MenuCategory.menu_id == menu_id,
                MenuCategory.tenant_id == user.tenant_id,
                MenuCategory.is_active == True,
            )
        )
        cat = res_cat.scalars().first()
        if not cat:
            return RedirectResponse(url=f"/admin/menu-items?menu_id={menu_id}&error=Invalid+category", status_code=303)

    photo_filename = None
    if photo and photo.filename:
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            return RedirectResponse(
                url=f"/admin/menu-items?menu_id={menu_id}&error=Unsupported+image+type",
                status_code=303,
            )

        # Build a stable Spaces object key
        photo_filename = (
            f"prod/tenants/{user.tenant_id}/menus/{menu_id}/items/"
            f"{uuid.uuid4().hex}{ext}"
        )

        contents = await photo.read()

        await put_public_object(
            key=photo_filename,
            body=contents,
            content_type=photo.content_type,
        )

    item = MenuItem(
        name=(name or "").strip(),
        description=(description or "").strip(),
        price=float(price),
        qty_available=int(quantity),
        menu_id=menu_id,
        category_id=(category_id or None),
        photo_filename=photo_filename,
    )
    db.add(item)
    await db.commit()

    return RedirectResponse(url=f"/admin/menu-items?menu_id={menu_id}&success=Item+added", status_code=303)

    # Validate category belongs to this menu + tenant (if provided)
    if category_id:
        cat_res = await db.execute(
            select(MenuCategory).where(
                MenuCategory.id == category_id,
                MenuCategory.menu_id == menu_id,
                MenuCategory.tenant_id == user.tenant_id,
            )
        )
        if not cat_res.scalar_one_or_none():
            return RedirectResponse(url="/admin/menu-items/create?error=Invalid+category", status_code=303)

    photo_filename = None
    if photo and photo.filename:
        try:
            photo_filename = await _save_uploaded_photo(photo, user.tenant_id)
        except ValueError as e:
            return RedirectResponse(url=f"/admin/menu-items/create?error={str(e).replace(' ', '+')}", status_code=303)

    new_item = MenuItem(
        name=name.strip(),
        description=(description.strip() if description else ""),
        price=float(price),
        qty_available=int(quantity),
        menu_id=menu_id,
        photo_filename=photo_filename,
        category_id=category_id,  # safe even if column exists; you ran migration
    )

    db.add(new_item)
    await db.commit()
    return RedirectResponse(url="/admin/menu-items?success=Item+Created", status_code=303)

# ----- Bulk Create Menu Items (JSON)
@router.post("/admin/menu-items/bulk-create")
async def bulk_create_menu_items(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    data = await request.json()
    menu_id = data.get("menu_id")
    items = data.get("items", [])

    if not menu_id:
        return RedirectResponse(url="/admin/menu-items/create?error=Missing+menu", status_code=303)

    menu = await _get_menu_for_tenant(db, menu_id, user.tenant_id)
    if not menu:
        return RedirectResponse(url="/admin/menu-items/create?error=Invalid+menu", status_code=303)

    # Collect category_ids from payload (optional) and validate them in ONE query
    raw_cat_ids = []
    for it in items:
        cid = it.get("category_id")
        if cid:
            raw_cat_ids.append(str(cid))

    allowed_category_ids = set()
    if raw_cat_ids:
        # Only categories that belong to THIS tenant + THIS menu are allowed
        cat_res = await db.execute(
            select(MenuCategory.id).where(
                MenuCategory.tenant_id == user.tenant_id,
                MenuCategory.menu_id == menu_id,
                MenuCategory.id.in_(raw_cat_ids),
                MenuCategory.is_active == True,
            )
        )
        allowed_category_ids = {row[0] for row in cat_res.all()}

    for item in items:
        item_name = (item.get("name") or "").strip()
        if not item_name:
            continue

        # defensive parsing
        try:
            price = float(item.get("price") or 0)
        except Exception:
            price = 0.0

        # support both keys: qty OR qty_available
        raw_qty = item.get("qty", None)
        if raw_qty is None:
            raw_qty = item.get("qty_available", 0)

        try:
            qty = int(raw_qty or 0)
        except Exception:
            qty = 0

        if qty < 0:
            qty = 0
        if price < 0:
            price = 0.0

        # category assignment (optional)
        category_id = item.get("category_id") or None
        if category_id:
            category_id = str(category_id)
            if category_id not in allowed_category_ids:
                # reject invalid category reference silently (or choose to error)
                category_id = None

        menu_item = MenuItem(
            name=item_name,
            description=(item.get("description") or "").strip(),
            price=price,
            qty_available=qty,
            menu_id=menu_id,
            category_id=category_id,
        )
        db.add(menu_item)

    await db.commit()
    return RedirectResponse(url="/admin/menu-items?success=Items+added", status_code=303)



@router.get("/admin/menu-items")
async def view_menu_items(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    menu_id = request.query_params.get("menu_id")

    # If no menu_id provided, default to active menu (or first menu)
    if not menu_id:
        res_active = await db.execute(
            select(Menu)
            .where(Menu.tenant_id == user.tenant_id, Menu.is_active == True)
            .limit(1)
        )
        active_menu = res_active.scalars().first()

        if active_menu:
            return RedirectResponse(url=f"/admin/menu-items?menu_id={active_menu.id}", status_code=303)

        # No active menu, fallback to first menu
        res_any = await db.execute(
            select(Menu).where(Menu.tenant_id == user.tenant_id).order_by(Menu.name.asc()).limit(1)
        )
        any_menu = res_any.scalars().first()
        if any_menu:
            return RedirectResponse(url=f"/admin/menu-items?menu_id={any_menu.id}", status_code=303)

        return templates.TemplateResponse(
            "menus/menu_items.html",
            {"request": request, "menus": [], "menu": None, "menu_categories_map": {}, "user": user},
        )

    # Load ONE menu, with items
    res_menu = await db.execute(
        select(Menu)
        .where(Menu.id == menu_id, Menu.tenant_id == user.tenant_id)
        .options(selectinload(Menu.items))
    )
    menu = res_menu.scalars().first()
    if not menu:
        return RedirectResponse(url="/admin/menus?error=Invalid+menu", status_code=303)

    # Load categories for THIS menu
    res_cats = await db.execute(
        select(MenuCategory)
        .where(
            MenuCategory.tenant_id == user.tenant_id,
            MenuCategory.menu_id == menu.id,
            MenuCategory.is_active == True,
        )
        .order_by(MenuCategory.display_order.asc(), MenuCategory.name.asc())
    )
    cats = res_cats.scalars().all()

    menu_categories_map = {menu.id: cats}

    return templates.TemplateResponse(
        "menus/menu_items.html",
        {
            "request": request,
            # keep template compatibility: provide menus list with one element
            "menus": [menu],
            "menu": menu,
            "menu_id": menu.id,
            "menu_categories_map": menu_categories_map,
            "user": user,
        },
    )

# ----- Inline Update (JSON)
@router.post("/admin/menu-items/{item_id}/inline-update")
async def inline_update_menu_item(
    item_id: str,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    item = await _get_item_for_tenant(db, item_id, user.tenant_id)
    if not item:
        return {"error": "Not found"}

    # Update allowed fields only
    if "name" in payload:
        item.name = (payload.get("name") or item.name).strip()

    if "description" in payload:
        item.description = payload.get("description", item.description)

    if "price" in payload:
        try:
            item.price = float(payload.get("price"))
        except (TypeError, ValueError):
            return {"error": "Invalid price"}

    if "qty_available" in payload:
        try:
            item.qty_available = int(payload.get("qty_available"))
        except (TypeError, ValueError):
            return {"error": "Invalid qty"}

    # Optional: allow category changes (template not wired yet)
    if "category_id" in payload:
        category_id = payload.get("category_id")
        if category_id:
            # validate category belongs to this item's menu and tenant
            cat_res = await db.execute(
                select(MenuCategory).where(
                    MenuCategory.id == category_id,
                    MenuCategory.menu_id == item.menu_id,
                    MenuCategory.tenant_id == user.tenant_id,
                )
            )
            if not cat_res.scalar_one_or_none():
                return {"error": "Invalid category"}
        item.category_id = category_id

    await db.commit()
    return {"status": "ok"}


# ----- Add single item (form-based)
@router.post("/admin/menu-items/add", response_class=RedirectResponse)
async def add_menu_item(
    request: Request,
    menu_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    price: float = Form(...),
    qty_available: int = Form(...),
    category_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    menu = await _get_menu_for_tenant(db, menu_id, user.tenant_id)
    if not menu:
        return RedirectResponse(url="/admin/menu-items?error=Invalid+menu", status_code=303)

    if category_id:
        cat_res = await db.execute(
            select(MenuCategory).where(
                MenuCategory.id == category_id,
                MenuCategory.menu_id == menu_id,
                MenuCategory.tenant_id == user.tenant_id,
            )
        )
        if not cat_res.scalar_one_or_none():
            return RedirectResponse(url="/admin/menu-items?error=Invalid+category", status_code=303)

    new_item = MenuItem(
        name=name.strip(),
        description=(description.strip() if description else ""),
        price=float(price),
        qty_available=int(qty_available),
        menu_id=menu_id,
        category_id=category_id,
    )
    db.add(new_item)
    await db.commit()
    return RedirectResponse(url="/admin/menu-items?success=Item+added", status_code=303)


# ----- Delete item
@router.post("/admin/menu-items/{item_id}/delete")
async def delete_menu_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    item = await _get_item_for_tenant(db, item_id, user.tenant_id)
    if item:
        await db.delete(item)
        await db.commit()

    return RedirectResponse(url="/admin/menu-items?success=Item+deleted", status_code=303)
