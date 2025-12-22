from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.auth.dependencies import get_current_customer, get_current_admin_user
from app.models.customer.customer import Customer
from app.models.customer.customer_order import CustomerOrder, OrderItem
from app.models.menu.menu import Menu
from app.models.menu.menu_item import MenuItem
from app.models.menu.menu_category import MenuCategory
from app.models.tenant import Tenant
from app.utils.email_service import send_new_order_email

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


# -----------------------
# Customer Auth / Landing
# -----------------------

@router.get("/customer/login", response_class=HTMLResponse)
async def customer_login_page(request: Request):
    return templates.TemplateResponse("login_customer.html", {"request": request})


@router.post("/customer/login", response_class=HTMLResponse)
async def customer_login_post(
    request: Request,
    pin_code: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    pin = (pin_code or "").strip()

    # IMPORTANT: scope by tenant is handled by customer record (pin is unique per tenant ideally).
    # If PIN is not tenant-unique globally, you should enforce uniqueness per tenant in DB.
    result = await db.execute(select(Customer).where(Customer.pin_code == pin))
    customer = result.scalar_one_or_none()

    if customer:
        request.session["user_id"] = customer.id
        request.session["role"] = "customer"
        request.session["tenant_id"] = customer.tenant_id
        # Redirect to the actual route, not a template filename
        return RedirectResponse("/customer", status_code=302)

    return templates.TemplateResponse(
        "login_customer.html",
        {"request": request, "error": "Invalid PIN. Please try again."},
    )


@router.get("/customer", response_class=HTMLResponse)
async def customer_landing(request: Request, user=Depends(get_current_customer)):
    return templates.TemplateResponse(
        "customer/customer_landing.html",
        {"request": request, "user": user},
    )


# -----------------------
# Customer Menu (Grouped)
# -----------------------

@router.get("/customer/menu", response_class=HTMLResponse)
async def view_customer_menu(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_customer),
):
    # Single-active-menu assumption (enforced by admin)
    res = await db.execute(
        select(Menu)
        .where(Menu.tenant_id == user.tenant_id, Menu.is_active == True)
        .options(selectinload(Menu.items))
    )
    active_menu = res.scalars().first()

    if not active_menu:
        return templates.TemplateResponse(
            "customer/customer_menu.html",
            {
                "request": request,
                "user": user,
                "menu": None,
                "category_groups": [],
                "error": "No active menu is available right now. Please check back soon.",
            },
        )

    # Load categories for this menu (active only)
    cat_res = await db.execute(
        select(MenuCategory)
        .where(
            MenuCategory.tenant_id == user.tenant_id,
            MenuCategory.menu_id == active_menu.id,
            MenuCategory.is_active == True,
        )
        .order_by(MenuCategory.display_order.asc(), MenuCategory.name.asc())
    )
    categories = cat_res.scalars().all()
    categories_by_id = {c.id: c for c in categories}

    # Group items by category_id, keep uncategorized bucket
    uncategorized = []
    grouped: dict[str, list[MenuItem]] = {c.id: [] for c in categories}

    # Keep only items with qty >= 0 (defensive)
    for it in (active_menu.items or []):
        if it.category_id and it.category_id in grouped:
            grouped[it.category_id].append(it)
        else:
            uncategorized.append(it)

    # Sort items within each category (name asc for now)
    for k in grouped:
        grouped[k] = sorted(grouped[k], key=lambda x: (x.name or "").lower())
    uncategorized = sorted(uncategorized, key=lambda x: (x.name or "").lower())

    # Build final render groups in order
    category_groups: list[dict[str, Any]] = []
    for c in categories:
        items = grouped.get(c.id, [])
        if not items:
            continue
        category_groups.append({"id": c.id, "name": c.name, "items": items})

    # Add uncategorized at bottom if any
    if uncategorized:
        category_groups.append({"id": None, "name": "Other", "items": uncategorized})

    return templates.TemplateResponse(
        "customer/customer_menu.html",
        {
            "request": request,
            "user": user,
            "menu": active_menu,
            "category_groups": category_groups,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        },
    )


# -----------------------
# Order Submission
# -----------------------

@router.post("/customer/order/submit-full")
async def submit_full_order(
    request: Request,
    cart_json: str = Form(...),
    note: str = Form(""),
    db: AsyncSession = Depends(get_db),
    customer=Depends(get_current_customer),
):
    # Parse cart
    try:
        cart = json.loads(cart_json)
    except json.JSONDecodeError:
        return RedirectResponse("/customer/menu?error=Invalid+cart", status_code=303)

    if not isinstance(cart, list) or not cart:
        return RedirectResponse("/customer/menu?error=Empty+cart", status_code=303)

    # Normalize and validate cart payload
    normalized: list[dict[str, Any]] = []
    for row in cart:
        try:
            item_id = str(row.get("id"))
            qty = int(row.get("quantity", 0))
        except Exception:
            continue
        if not item_id or qty <= 0:
            continue
        normalized.append({"id": item_id, "quantity": qty})

    if not normalized:
        return RedirectResponse("/customer/menu?error=Empty+cart", status_code=303)

    # Create order (total_price will be calculated as we add items)
    order = CustomerOrder(
        customer_id=customer.id,
        tenant_id=customer.tenant_id,
        note=(note or "").strip(),
        total_price=0.00,  # Will be updated as items are added
    )
    db.add(order)
    await db.flush()  # populate order.id

    # Load all menu items referenced, ensure they belong to this tenant via menu->tenant
    item_ids = [x["id"] for x in normalized]
    items_res = await db.execute(
        select(MenuItem)
        .where(MenuItem.id.in_(item_ids))
        .options(selectinload(MenuItem.menu))
    )
    fetched_items = items_res.scalars().all()

    # Filter to tenant-safe items only
    safe_items: dict[str, MenuItem] = {}
    for it in fetched_items:
        if it.menu and it.menu.tenant_id == customer.tenant_id:
            safe_items[it.id] = it

    # Validate availability + create order items
    items_summary = []  # for email
    order_total = 0.00

    for row in normalized:
        menu_item = safe_items.get(row["id"])
        if not menu_item:
            await db.rollback()
            return RedirectResponse("/customer/menu?error=Invalid+item+in+cart", status_code=303)

        qty_requested = int(row["quantity"])
        qty_available = int(menu_item.qty_available or 0)

        if qty_requested > qty_available:
            await db.rollback()
            return RedirectResponse("/customer/menu?error=Not+enough+inventory", status_code=303)

        # Get price at time of order
        item_price = float(menu_item.price or 0.00)
        line_total = item_price * qty_requested
        order_total += line_total

        # Create OrderItem row with snapshot data
        db.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=menu_item.id,
                quantity=qty_requested,
                price_at_time_of_order=item_price,
                item_name=menu_item.name,
            )
        )

        # Decrement inventory
        menu_item.qty_available = qty_available - qty_requested

        items_summary.append({
            "name": menu_item.name,
            "qty": qty_requested,
            "price": item_price,
            "total": line_total
        })

    # Update order total
    order.total_price = order_total

    await db.commit()

    # Send email notification if configured (using fresh session to avoid state issues)
    try:
        # Use a new database session for email to avoid transaction state issues
        from app.db import async_session
        async with async_session() as email_db:
            # Load tenant to get email configuration
            tenant_result = await email_db.execute(
                select(Tenant).where(Tenant.id == customer.tenant_id)
            )
            tenant = tenant_result.scalar_one_or_none()

            if tenant:
                email_result = send_new_order_email(
                    tenant=tenant,
                    customer=customer,
                    items_summary=items_summary,
                    order_id=order.id,
                    order_note=note or "",
                    order_total=order_total,
                )

                # Log result but don't fail order if email fails
                if email_result["success"]:
                    print(f"✅ Order email sent: {email_result['message']}")
                else:
                    print(f"⚠️ Order email not sent: {email_result['message']}")

    except Exception as e:
        # Keep order successful even if email fails
        print(f"❌ Email notification failed: {e}")

    return RedirectResponse("/customer/menu?success=Order+submitted!", status_code=303)


# Keep the legacy single-item submit if you still use it anywhere (optional)
@router.post("/customer/order/submit")
async def submit_order(
    request: Request,
    menu_item_id: str = Form(...),
    quantity: int = Form(...),
    db: AsyncSession = Depends(get_db),
    customer=Depends(get_current_customer),
):
    # Convert to full cart flow for consistency
    cart = [{"id": menu_item_id, "quantity": quantity}]
    return await submit_full_order(
        request=request,
        cart_json=json.dumps(cart),
        note="",
        db=db,
        customer=customer,
    )


# -----------------------
# Admin: Customers
# -----------------------

@router.get("/admin/customers/create", response_class=HTMLResponse)
async def create_customer_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    customers_res = await db.execute(
        select(Customer)
        .where(Customer.tenant_id == user.tenant_id)
        .order_by(Customer.name.asc())
    )
    customer_list = customers_res.scalars().all()

    return templates.TemplateResponse(
        "create_customer.html",
        {"request": request, "customers": customer_list, "user": user},
    )


@router.post("/admin/customers/create")
async def create_customer(
    request: Request,
    name: str = Form(...),
    pin_code: str = Form(...),
    phone_number: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    new_customer = Customer(
        name=(name or "").strip(),
        pin_code=(pin_code or "").strip(),
        phone_number=(phone_number or "").strip(),
        tenant_id=user.tenant_id,
    )
    db.add(new_customer)
    await db.commit()

    return RedirectResponse(
        url="/admin/customers/create?success=Customer+added+successfully",
        status_code=303,
    )


@router.post("/admin/customers/{customer_id}/delete")
async def delete_customer(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    result = await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.tenant_id == user.tenant_id)
    )
    customer = result.scalar_one_or_none()

    if customer:
        await db.delete(customer)
        await db.commit()

    return RedirectResponse(url="/admin/customers/create?success=Customer+deleted", status_code=303)


# -----------------------
# Admin: Orders
# -----------------------

@router.get("/admin/orders", response_class=HTMLResponse)
async def admin_view_orders(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    result = await db.execute(
        select(CustomerOrder)
        .options(
            selectinload(CustomerOrder.customer),
            selectinload(CustomerOrder.items).selectinload(OrderItem.menu_item),
        )
        .where(CustomerOrder.tenant_id == user.tenant_id)
        .order_by(CustomerOrder.timestamp.desc())
    )
    orders = result.scalars().all()

    filter_param = request.query_params.get("filter", "ALL")
    return templates.TemplateResponse(
        "admin_view_orders.html",
        {"request": request, "orders": orders, "user": user, "filter": filter_param},
    )


@router.post("/admin/orders/{order_id}/update_status")
async def update_order_status(
    order_id: str,
    status: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_admin_user),
):
    result = await db.execute(
        select(CustomerOrder).where(CustomerOrder.id == order_id, CustomerOrder.tenant_id == user.tenant_id)
    )
    order = result.scalar_one_or_none()

    if order:
        order.status = (status or "").strip()
        await db.commit()

    return RedirectResponse(url="/admin/orders?success=Order+updated", status_code=303)
