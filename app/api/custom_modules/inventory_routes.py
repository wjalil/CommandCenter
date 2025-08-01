from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from app.db import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.templating import Jinja2Templates
from app.auth.dependencies import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/modules/inventory", response_class=HTMLResponse)
async def inventory_module(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)  # ✅ Enforce tenant session
):
    return templates.TemplateResponse("custom_modules/inventory.html", {"request": request})