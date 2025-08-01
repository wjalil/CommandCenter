from fastapi import Request, Form, Depends,APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db import get_db
from app.models.customer.customer import Customer
from app.auth.dependencies import get_current_user

templates = Jinja2Templates(directory="app/templates")

router = APIRouter()

@router.get("/customer/login", response_class=HTMLResponse)
async def customer_login_page(request: Request):
    return templates.TemplateResponse("login_customer.html", {"request": request})

@router.post("/customer/login", response_class=HTMLResponse)
async def customer_login_post(
    request: Request,
    pin_code: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Customer).where(Customer.pin_code == pin_code))
    customer = result.scalar_one_or_none()

    if customer:
        request.session["user_id"] = customer.id
        request.session["role"] = "customer"
        request.session["tenant_id"] = customer.tenant_id 
        return RedirectResponse(f"/customer/menu", status_code=302)

    return templates.TemplateResponse("login_customer.html", {
        "request": request,
        "error": "Invalid PIN. Please try again.",
    })

@router.get("/admin/customers/create")
async def create_customer_form(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    customers = await db.execute(
        select(Customer).where(Customer.tenant_id == user.tenant_id)
    )
    customer_list = customers.scalars().all()
    return templates.TemplateResponse("create_customer.html", {
        "request": request,
        "customers": customer_list,
        "user": user
    })



@router.post("/admin/customers/create")
async def create_customer(
    request: Request,
    name: str = Form(...),
    pin_code: str = Form(...),
    phone_number: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
    
):
    new_customer = Customer(name=name, pin_code=pin_code, tenant_id=user.tenant_id,phone_number=phone_number)
    db.add(new_customer)
    await db.commit()
    return RedirectResponse(
        url=str(request.url_for("create_customer")) + "?success=Customer%20added%20successfully!",
        status_code=303
    )


@router.post("/admin/customers/{customer_id}/delete")
async def delete_customer(customer_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.tenant_id == user.tenant_id)
    )
    customer = result.scalar_one_or_none()
    if customer:
        await db.delete(customer)
        await db.commit()
    return RedirectResponse(url="/admin/customers/create", status_code=303)