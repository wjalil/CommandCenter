from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from app.db import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/modules/vending_form", response_class=HTMLResponse)
async def inventory_module(request: Request, db: AsyncSession = Depends(get_db)):
    return templates.TemplateResponse("custom_modules/inventory.html", {"request": request})
