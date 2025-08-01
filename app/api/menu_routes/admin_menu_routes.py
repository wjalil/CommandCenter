from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.menu.menu import Menu
from app.auth.dependencies import get_current_admin_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# ----- View All Menus
@router.get("/admin/menus")
async def view_menus(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_admin_user)):
    result = await db.execute(select(Menu).where(Menu.tenant_id == user.tenant_id))
    menus = result.scalars().all()
    return templates.TemplateResponse("menus/menus.html", {"request": request, "menus": menus})


# ----- Create Menu (GET + POST)
@router.get("/admin/menus/create")
async def create_menu_form(request: Request):
    return templates.TemplateResponse("/menus/create_menu.html", {"request": request})


@router.post("/admin/menus/create")
async def create_menu(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    is_active: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user)
):
    # If setting this menu active, make all others inactive
    if is_active:
        await db.execute(
            Menu.__table__.update()
            .where(Menu.tenant_id == user.tenant_id)
            .values(is_active=False)
        )
        await db.execute(
            Menu.__table__.update()
            .where(Menu.tenant_id == user.tenant_id)
            .values(is_active=False)
        )

    menu = Menu(
        name=name,
        description=description,
        is_active=is_active,
        tenant_id=user.tenant_id
    )
    db.add(menu)
    await db.commit()
    return RedirectResponse(url="/admin/menus", status_code=303)


