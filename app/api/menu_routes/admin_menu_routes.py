from typing import Optional, List

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, delete

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.menu.menu import Menu
from app.models.menu.menu_category import MenuCategory
from app.models.menu.menu_item import MenuItem  # ensure this exists + correct import

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ----- View All Menus (shows active + inactive)
@router.get("/admin/menus")
async def view_menus(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    result = await db.execute(
        select(Menu)
        .where(Menu.tenant_id == user.tenant_id)
        .order_by(Menu.name.asc())
    )
    menus = result.scalars().all()

    counts_res = await db.execute(
        select(MenuCategory.menu_id, func.count(MenuCategory.id))
        .where(MenuCategory.tenant_id == user.tenant_id, MenuCategory.is_active == True)
        .group_by(MenuCategory.menu_id)
    )
    menu_category_counts = {menu_id: cnt for menu_id, cnt in counts_res.all()}

    return templates.TemplateResponse(
        "menus/menus.html",
        {
            "request": request,
            "menus": menus,
            "menu_category_counts": menu_category_counts,
            "user": user,
        },
    )


# ----- Create Menu (GET)
@router.get("/admin/menus/create")
async def create_menu_form(request: Request, user=Depends(get_current_admin_user)):
    return templates.TemplateResponse(
        "menus/create_menu.html",
        {"request": request, "user": user},
    )


# ----- Create Menu (POST)
@router.post("/admin/menus/create")
async def create_menu(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    is_active: Optional[str] = Form(None),

    category_names: List[str] = Form([]),
    category_orders: List[str] = Form([]),

    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    menu_name = (name or "").strip()
    if not menu_name:
        return RedirectResponse(url="/admin/menus/create?error=Menu+name+required", status_code=303)

    menu_description = (description or "").strip()
    make_active = is_active is not None

    if make_active:
        await db.execute(
            Menu.__table__.update()
            .where(Menu.tenant_id == user.tenant_id)
            .values(is_active=False)
        )

    menu = Menu(
        name=menu_name,
        description=menu_description,
        is_active=make_active,
        tenant_id=user.tenant_id,
    )
    db.add(menu)
    await db.flush()

    cleaned = []
    seen = set()
    for i, raw_name in enumerate(category_names or []):
        cat_name = (raw_name or "").strip()
        if not cat_name:
            continue
        norm = " ".join(cat_name.lower().split())
        if norm in seen:
            continue
        seen.add(norm)

        display_order = i
        if i < len(category_orders or []):
            try:
                display_order = int(category_orders[i])
            except Exception:
                display_order = i

        cleaned.append((cat_name, display_order))

    if not cleaned:
        cleaned = [("Main", 0)]

    for cat_name, display_order in cleaned:
        db.add(MenuCategory(
            tenant_id=user.tenant_id,
            menu_id=menu.id,
            name=cat_name,
            display_order=display_order,
            is_active=True,
        ))

    await db.commit()
    return RedirectResponse(url="/admin/menus?success=Menu+created", status_code=303)


# ----- Activate / Deactivate Menu (POST)
@router.post("/admin/menus/{menu_id}/set-status")
async def set_menu_status(
    menu_id: str,
    action: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    result = await db.execute(
        select(Menu).where(Menu.id == menu_id, Menu.tenant_id == user.tenant_id)
    )
    menu = result.scalar_one_or_none()
    if not menu:
        return RedirectResponse(url="/admin/menus?error=Menu+not+found", status_code=303)

    action = (action or "").strip().lower()

    if action == "activate":
        await db.execute(
            Menu.__table__.update()
            .where(Menu.tenant_id == user.tenant_id)
            .values(is_active=False)
        )
        menu.is_active = True
    elif action == "deactivate":
        menu.is_active = False
    else:
        return RedirectResponse(url="/admin/menus?error=Invalid+action", status_code=303)

    await db.commit()
    return RedirectResponse(url="/admin/menus?success=Menu+updated", status_code=303)


# ----- Categories JSON for Menu Builder UI
@router.get("/admin/menus/{menu_id}/categories.json")
async def menu_categories_json(
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    res = await db.execute(
        select(Menu).where(Menu.id == menu_id, Menu.tenant_id == user.tenant_id)
    )
    menu = res.scalar_one_or_none()
    if not menu:
        return {"categories": []}

    cat_res = await db.execute(
        select(MenuCategory)
        .where(
            MenuCategory.menu_id == menu_id,
            MenuCategory.tenant_id == user.tenant_id,
            MenuCategory.is_active == True,
        )
        .order_by(MenuCategory.display_order.asc(), MenuCategory.name.asc())
    )
    cats = cat_res.scalars().all()

    return {"categories": [{"id": c.id, "name": c.name} for c in cats]}


# ===========================
# NEW: Edit Menu (GET)
# ===========================
@router.get("/admin/menus/{menu_id}/edit")
async def edit_menu_form(
    menu_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    res = await db.execute(
        select(Menu).where(Menu.id == menu_id, Menu.tenant_id == user.tenant_id)
    )
    menu = res.scalar_one_or_none()
    if not menu:
        return RedirectResponse(url="/admin/menus?error=Menu+not+found", status_code=303)

    cat_res = await db.execute(
        select(MenuCategory)
        .where(MenuCategory.menu_id == menu_id, MenuCategory.tenant_id == user.tenant_id)
        .order_by(MenuCategory.display_order.asc(), MenuCategory.name.asc())
    )
    categories = cat_res.scalars().all()

    return templates.TemplateResponse(
        "menus/edit_menu.html",
        {"request": request, "menu": menu, "categories": categories, "user": user},
    )


# ===========================
# NEW: Edit Menu (POST)
# ===========================
@router.post("/admin/menus/{menu_id}/edit")
async def edit_menu_post(
    menu_id: str,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    is_active: Optional[str] = Form(None),

    # Existing categories (parallel arrays)
    category_ids: List[str] = Form([]),
    category_names: List[str] = Form([]),
    category_orders: List[str] = Form([]),
    category_active: List[str] = Form([]),  # checkbox => includes id when checked

    # New categories
    new_category_names: List[str] = Form([]),
    new_category_orders: List[str] = Form([]),

    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    res = await db.execute(
        select(Menu).where(Menu.id == menu_id, Menu.tenant_id == user.tenant_id)
    )
    menu = res.scalar_one_or_none()
    if not menu:
        return RedirectResponse(url="/admin/menus?error=Menu+not+found", status_code=303)

    menu_name = (name or "").strip()
    if not menu_name:
        return RedirectResponse(url=f"/admin/menus/{menu_id}/edit?error=Menu+name+required", status_code=303)

    menu.name = menu_name
    menu.description = (description or "").strip()

    make_active = is_active is not None
    if make_active:
        await db.execute(
            Menu.__table__.update()
            .where(Menu.tenant_id == user.tenant_id)
            .values(is_active=False)
        )
        menu.is_active = True
    # If unchecked, do not auto-deactivate here unless you want that behavior:
    # else: menu.is_active = False

    active_set = set(category_active or [])

    # Update existing categories safely
    # (soft-delete by is_active=False when unchecked)
    for i, cid in enumerate(category_ids or []):
        cid = (cid or "").strip()
        if not cid:
            continue

        cat_res = await db.execute(
            select(MenuCategory).where(
                MenuCategory.id == cid,
                MenuCategory.menu_id == menu_id,
                MenuCategory.tenant_id == user.tenant_id,
            )
        )
        cat = cat_res.scalar_one_or_none()
        if not cat:
            continue

        nm = ""
        if i < len(category_names or []):
            nm = (category_names[i] or "").strip()

        if nm:
            cat.name = nm

        try:
            if i < len(category_orders or []):
                cat.display_order = int(category_orders[i])
        except Exception:
            pass

        cat.is_active = (cid in active_set)

    # Add new categories
    for j, raw in enumerate(new_category_names or []):
        nm = (raw or "").strip()
        if not nm:
            continue
        order = 0
        try:
            if j < len(new_category_orders or []):
                order = int(new_category_orders[j])
            else:
                order = 0
        except Exception:
            order = 0

        db.add(MenuCategory(
            tenant_id=user.tenant_id,
            menu_id=menu_id,
            name=nm,
            display_order=order,
            is_active=True,
        ))

    await db.commit()
    return RedirectResponse(url=f"/admin/menus/{menu_id}/edit?success=Menu+updated", status_code=303)


# ===========================
# NEW: Delete Menu (POST)
# ===========================
@router.post("/admin/menus/{menu_id}/delete")
async def delete_menu(
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    res = await db.execute(
        select(Menu).where(Menu.id == menu_id, Menu.tenant_id == user.tenant_id)
    )
    menu = res.scalar_one_or_none()
    if not menu:
        return RedirectResponse(url="/admin/menus?error=Menu+not+found", status_code=303)

    # Hard-delete dependent rows to avoid FK constraints if cascade isn't configured
    await db.execute(
        delete(MenuItem).where(MenuItem.menu_id == menu_id)
    )
    await db.execute(
        delete(MenuCategory).where(MenuCategory.menu_id == menu_id)
    )
    await db.delete(menu)

    await db.commit()
    return RedirectResponse(url="/admin/menus?success=Menu+deleted", status_code=303)
