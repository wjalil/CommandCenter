from fastapi import Request, Form, Depends,APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db import get_db
from app.models.customer.customer import Customer
from app.auth.dependencies import get_current_user, get_current_customer
from app.models.menu.menu import Menu
from app.models.menu.menu_item import MenuItem
from sqlalchemy.orm import selectinload
from app.models.customer.customer_order import CustomerOrder, OrderItem
import json

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
        return RedirectResponse(f"/customer/customer_landing.html", status_code=302)

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

@router.get("/customer")
async def customer_landing(request: Request, user=Depends(get_current_customer)):
    return templates.TemplateResponse("customer/customer_landing.html", {
        "request": request,
        "user": user
    })


@router.get("/customer/menu")
async def view_customer_menu(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_customer)
):
    result = await db.execute(
        select(Menu)
        .where(Menu.tenant_id == user.tenant_id, Menu.is_active == True)
        .options(selectinload(Menu.items))
    )
    menus = result.scalars().all()

    return templates.TemplateResponse("customer/customer_menu.html", {
        "request": request,
        "menus": menus,
        "user": user
    })


@router.post("/customer/order/submit")
async def submit_order(
    request: Request,
    menu_item_id: str = Form(...),
    quantity: int = Form(...),
    db: AsyncSession = Depends(get_db),
    customer=Depends(get_current_customer)
):
    # Create a new order for the current customer
    order = CustomerOrder(
        customer_id=customer.id,
        tenant_id=customer.tenant_id,
    )
    db.add(order)
    await db.flush()  # to populate order.id for FK in OrderItem

    # Add the ordered item
    order_item = OrderItem(
        order_id=order.id,
        menu_item_id=menu_item_id,
        quantity=quantity
    )
    db.add(order_item)
    await db.commit()

    return RedirectResponse("/customer/menu?success=Order+Placed", status_code=303)


@router.post("/customer/order/submit-full")
async def submit_full_order(
    request: Request,
    cart_json: str = Form(...),
    note: str = Form(""),
    db: AsyncSession = Depends(get_db),
    customer=Depends(get_current_customer)
):
    try:
        cart = json.loads(cart_json)
    except json.JSONDecodeError:
        return RedirectResponse("/customer/menu?error=Invalid+cart", status_code=302)

    if not cart:
        return RedirectResponse("/customer/menu?error=Empty+cart", status_code=302)

    # 🧾 Create the order
    order = CustomerOrder(
        customer_id=customer.id,
        tenant_id=customer.tenant_id,
        note=note
    )
    db.add(order)
    await db.flush()  # populate order.id

    # 🛒 Add each item
    for item in cart:
        order_item = OrderItem(
            order_id=order.id,
            menu_item_id=item["id"],
            quantity=item["quantity"]
        )
        db.add(order_item)

        # Optional: Reduce quantity available
        result = await db.execute(select(MenuItem).where(MenuItem.id == item["id"]))
        menu_item = result.scalar_one_or_none()
        if menu_item:
            menu_item.qty_available -= item["quantity"]

    await db.commit()

    return RedirectResponse("/customer/menu?success=Order+submitted!", status_code=303)

#--- Admin Routes -- 
@router.get("/admin/orders")
async def admin_view_orders(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(
        select(CustomerOrder)
        .options(selectinload(CustomerOrder.customer), selectinload(CustomerOrder.items).selectinload(OrderItem.menu_item))
        .where(CustomerOrder.tenant_id == user.tenant_id)
        .order_by(CustomerOrder.timestamp.desc())
    )
    orders = result.scalars().all()
    return templates.TemplateResponse("admin_view_orders.html", {"request": request, "orders": orders, "user": user})


@router.post("/admin/orders/{order_id}/update_status")
async def update_order_status(order_id: str, status: str = Form(...), db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(
        select(CustomerOrder).where(CustomerOrder.id == order_id, CustomerOrder.tenant_id == user.tenant_id)
    )
    order = result.scalar_one_or_none()
    if order:
        order.status = status
        await db.commit()
    return RedirectResponse(url="/admin/orders", status_code=303)
