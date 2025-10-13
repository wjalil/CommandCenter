from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.customer.customer import Customer
from app.db import get_db
from app.models.user import User

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})


# 🔐 Shared PIN login handler
async def handle_pin_login(request, role, pin_code, db):
    if role == "customer":
        result = await db.execute(select(Customer).where(Customer.pin_code == pin_code))
        customer = result.scalar_one_or_none()

        if customer:
            request.session["user_id"] = customer.id
            request.session["role"] = "customer"
            request.session["tenant_id"] = customer.tenant_id
            return RedirectResponse(url="/customer/", status_code=302)

    else:
        result = await db.execute(select(User).where(User.pin_code == pin_code, User.role == role))
        user = result.scalar_one_or_none()

        if user:
            request.session["user_id"] = user.id
            request.session["role"] = user.role
            request.session["tenant_id"] = user.tenant_id

            if role == "admin":
                return RedirectResponse(url="/admin/dashboard", status_code=302)
            elif role == "worker":
                # ✅ Redirect worker to new home page instead of shifts
                return RedirectResponse(url="/worker/home", status_code=302)

    # ❌ Invalid login
    return templates.TemplateResponse("landing.html", {
        "request": request,
        "error": "Invalid PIN or role.",
    })


@router.get("/login/{role}", response_class=HTMLResponse)
async def login_get(request: Request, role: str):
    if role not in ["admin", "worker", "customer"]:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login_pin.html", {"request": request, "role": role})


@router.post("/login/{role}", response_class=HTMLResponse)
async def login_post(request: Request, role: str, pin_code: str = Form(...), db: AsyncSession = Depends(get_db)):
    return await handle_pin_login(request, role, pin_code, db)


@router.get("/home")
async def redirect_home(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    role = request.session.get("role")

    if not user_id or not role:
        return RedirectResponse(url="/", status_code=302)

    if role == "admin":
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    if role == "customer":
        return RedirectResponse(url="/customer/customer_landing.html", status_code=302)

    # ✅ Worker: redirect to new home landing page
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user:
        return RedirectResponse(url="/worker/home", status_code=302)

    return RedirectResponse(url="/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)
