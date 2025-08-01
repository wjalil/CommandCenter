from fastapi import APIRouter, Depends, Request, Form , Body
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.menu.menu_item import MenuItem
from app.models.menu.menu import Menu
from sqlalchemy.orm import selectinload

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# ----- Render Menu Builder Page
@router.get("/admin/menu-items/create")
async def menu_builder_page(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_admin_user)):
    result = await db.execute(select(Menu).where(Menu.tenant_id == user.tenant_id))
    menus = result.scalars().all()
    return templates.TemplateResponse("menus/menu_builder.html", {"request": request, "menus": menus})


# ----- Bulk Create Menu Items
@router.post("/admin/menu-items/bulk-create")
async def bulk_create_menu_items(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_admin_user)):
    data = await request.json()
    menu_id = data.get("menu_id")
    items = data.get("items", [])

    # Optional: validate the menu belongs to this tenant
    menu_result = await db.execute(select(Menu).where(Menu.id == menu_id, Menu.tenant_id == user.tenant_id))
    if not menu_result.scalar_one_or_none():
        return RedirectResponse(url="/admin/menu-items/create?error=Invalid+menu", status_code=303)

    for item in items:
        menu_item = MenuItem(
            name=item["name"],
            description=item.get("description", ""),
            price=item["price"],
            qty_available=item["qty"],
            menu_id=menu_id
        )
        db.add(menu_item)

    await db.commit()
    return RedirectResponse(url="/admin/menu-items?success=Items%20added", status_code=303)

@router.get("/admin/menu-items")
async def view_menu_items(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_admin_user)):
    result = await db.execute(
        select(Menu)
        .where(Menu.tenant_id == user.tenant_id)
        .options(selectinload(Menu.items))  # eager load items
    )
    menus = result.scalars().all()
    return templates.TemplateResponse("menus/menu_items.html", {"request": request, "menus": menus})


#Post Edit
@router.post("/admin/menu-items/{item_id}/inline-update")
async def inline_update_menu_item(
    item_id: str,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user)
):
    result = await db.execute(
        select(MenuItem).where(MenuItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        return {"error": "Item not found"}

    # validate menu ownership
    menu_result = await db.execute(
        select(Menu).where(Menu.id == item.menu_id, Menu.tenant_id == user.tenant_id)
    )
    if not menu_result.scalar_one_or_none():
        return {"error": "Forbidden"}

    item.name = payload.get("name", item.name)
    item.description = payload.get("description", item.description)
    item.price = payload.get("price", item.price)
    item.qty_available = payload.get("qty_available", item.qty_available)

    await db.commit()
    return {"status": "ok"}


#Backend Route for Adding a Single Item
@router.post("/admin/menu-items/add", response_class=RedirectResponse)
async def add_menu_item(
    request: Request,
    menu_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    price: float = Form(...),
    qty_available: int = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user)
):
    result = await db.execute(select(Menu).where(Menu.id == menu_id, Menu.tenant_id == user.tenant_id))
    menu = result.scalar_one_or_none()

    if not menu:
        return RedirectResponse(url="/admin/menu-items?error=Invalid+menu", status_code=303)

    new_item = MenuItem(
        name=name,
        description=description,
        price=price,
        qty_available=qty_available,
        menu_id=menu_id
    )
    db.add(new_item)
    await db.commit()
    return RedirectResponse(url="/admin/menu-items?success=Item+added", status_code=303)

#Post Delete
@router.post("/admin/menu-items/{item_id}/delete")
async def delete_menu_item(item_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_admin_user)):
    result = await db.execute(select(MenuItem).where(MenuItem.id == item_id))
    item = result.scalar_one_or_none()

    if item:
        # Validate ownership via menu → tenant check
        menu_result = await db.execute(
            select(Menu).where(Menu.id == item.menu_id, Menu.tenant_id == user.tenant_id)
        )
        menu = menu_result.scalar_one_or_none()
        if not menu:
            return RedirectResponse(url="/admin/menu-items", status_code=303)

        # Safe to delete
        await db.delete(item)
        await db.commit()

    return RedirectResponse(url="/admin/menu-items?success=Item%20deleted", status_code=303)
