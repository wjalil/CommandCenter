# auth/dependencies.py
from fastapi import Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.db import get_db
from app.models.user import User
from app.models.customer.customer import Customer


class PortalAuthRequired(Exception):
    """Raised when a catering-client-portal page is hit without a valid session.
    Caught by an exception handler in main.py that redirects to the login page
    (instead of surfacing a raw 401 JSON body to a client-facing user)."""
    pass

async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

async def get_current_admin_user(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access only")
    return user

async def get_current_admin_or_office(user: User = Depends(get_current_user)):
    """Allows both full admins and office admins (e.g. auto shop staff)."""
    if user.role not in ("admin", "office_admin"):
        raise HTTPException(status_code=403, detail="Access denied")
    return user

async def get_current_admin_or_worker(user: User = Depends(get_current_user)):
    """Allows admins and workers (e.g. production sheet, driver view)."""
    if user.role not in ("admin", "office_admin", "worker"):
        raise HTTPException(status_code=403, detail="Access denied")
    return user

async def get_current_customer(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    user_id = request.session.get("user_id")
    role = request.session.get("role")

    if not user_id or role != "customer":
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(select(Customer).where(Customer.id == user_id))
    customer = result.scalar_one_or_none()

    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    return customer

async def get_current_catering_client(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    from app.models.catering.client_account import CateringClientAccount

    account_id = request.session.get("user_id")
    role = request.session.get("role")

    if not account_id or role != "catering_client":
        raise PortalAuthRequired()

    result = await db.execute(
        select(CateringClientAccount)
        .options(selectinload(CateringClientAccount.program))
        .where(CateringClientAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account or not account.is_active:
        raise PortalAuthRequired()

    return account