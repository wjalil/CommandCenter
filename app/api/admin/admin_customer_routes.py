# app/api/admin/admin_customer_routes.py

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_
from datetime import datetime
from decimal import Decimal

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.customer.customer import Customer
from app.models.customer.customer_order import CustomerOrder, OrderItem, PaymentStatus
from app.models.menu.menu_item import MenuItem

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


@router.get("/admin/customers/balances", response_class=HTMLResponse)
async def customer_balances(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    """Display customer balances - showing unpaid order totals"""

    # Get all customers for this tenant with their unpaid order totals
    result = await db.execute(
        select(
            Customer.id,
            Customer.name,
            Customer.phone_number,
            func.coalesce(func.sum(CustomerOrder.total_price), 0).label('balance'),
            func.count(CustomerOrder.id).label('unpaid_order_count')
        )
        .outerjoin(
            CustomerOrder,
            and_(
                CustomerOrder.customer_id == Customer.id,
                CustomerOrder.payment_status == PaymentStatus.UNPAID
            )
        )
        .where(Customer.tenant_id == user.tenant_id)
        .group_by(Customer.id, Customer.name, Customer.phone_number)
        .order_by(func.coalesce(func.sum(CustomerOrder.total_price), 0).desc())
    )

    customers = result.all()

    return templates.TemplateResponse(
        "admin/customer_balances.html",
        {
            "request": request,
            "user": user,
            "customers": customers,
        }
    )


@router.get("/admin/customers/{customer_id}/orders", response_class=HTMLResponse)
async def customer_orders(
    request: Request,
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    """Display all orders for a specific customer"""

    # Get customer
    customer_result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.tenant_id == user.tenant_id
        )
    )
    customer = customer_result.scalar_one_or_none()

    if not customer:
        return RedirectResponse("/admin/customers/balances?error=Customer+not+found", status_code=303)

    # Get all orders with items
    orders_result = await db.execute(
        select(CustomerOrder)
        .where(CustomerOrder.customer_id == customer_id)
        .order_by(CustomerOrder.timestamp.desc())
    )
    orders = orders_result.scalars().all()

    # Load order items for each order
    for order in orders:
        items_result = await db.execute(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
        order.items_list = items_result.scalars().all()

    return templates.TemplateResponse(
        "admin/customer_orders.html",
        {
            "request": request,
            "user": user,
            "customer": customer,
            "orders": orders,
        }
    )


@router.post("/admin/orders/{order_id}/mark-paid")
async def mark_order_paid(
    order_id: str,
    payment_method: str = Form("Cash"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    """Mark an order as paid"""

    # Get the order
    result = await db.execute(
        select(CustomerOrder)
        .join(Customer)
        .where(
            CustomerOrder.id == order_id,
            Customer.tenant_id == user.tenant_id
        )
    )
    order = result.scalar_one_or_none()

    if not order:
        return RedirectResponse("/admin/customers/balances?error=Order+not+found", status_code=303)

    # Update payment status
    order.payment_status = PaymentStatus.PAID
    order.payment_method = payment_method
    order.paid_at = datetime.utcnow()

    await db.commit()

    return RedirectResponse(
        f"/admin/customers/{order.customer_id}/orders?success=Order+marked+as+paid",
        status_code=303
    )


@router.post("/admin/orders/{order_id}/mark-unpaid")
async def mark_order_unpaid(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    """Mark an order as unpaid"""

    # Get the order
    result = await db.execute(
        select(CustomerOrder)
        .join(Customer)
        .where(
            CustomerOrder.id == order_id,
            Customer.tenant_id == user.tenant_id
        )
    )
    order = result.scalar_one_or_none()

    if not order:
        return RedirectResponse("/admin/customers/balances?error=Order+not+found", status_code=303)

    # Update payment status
    order.payment_status = PaymentStatus.UNPAID
    order.payment_method = None
    order.paid_at = None

    await db.commit()

    return RedirectResponse(
        f"/admin/customers/{order.customer_id}/orders?success=Order+marked+as+unpaid",
        status_code=303
    )
