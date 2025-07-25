from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.templating import Jinja2Templates
from app.db import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/modules/driver_order", response_class=HTMLResponse)
async def driver_order_module(request: Request, db: AsyncSession = Depends(get_db)):
    return templates.TemplateResponse("custom_modules/driver_order.html", {"request": request})
