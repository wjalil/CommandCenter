from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.models.catering.portal_request import ClientPortalRequest


async def create_request(
    db: AsyncSession,
    program_id: str,
    tenant_id: int,
    client_account_id: str,
    request_type: str,
    message: str,
    proposed_counts: Optional[str] = None,
):
    req = ClientPortalRequest(
        program_id=program_id,
        tenant_id=tenant_id,
        client_account_id=client_account_id,
        request_type=request_type,
        message=message,
        proposed_counts=proposed_counts,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req


async def get_requests_for_program(db: AsyncSession, program_id: str, tenant_id: int):
    result = await db.execute(
        select(ClientPortalRequest)
        .where(
            ClientPortalRequest.program_id == program_id,
            ClientPortalRequest.tenant_id == tenant_id,
        )
        .order_by(ClientPortalRequest.created_at.desc())
    )
    return result.scalars().all()


async def get_requests_for_tenant(db: AsyncSession, tenant_id: int, status: Optional[str] = None):
    query = (
        select(ClientPortalRequest)
        .options(selectinload(ClientPortalRequest.program))
        .where(ClientPortalRequest.tenant_id == tenant_id)
    )
    if status:
        query = query.where(ClientPortalRequest.status == status)
    query = query.order_by(ClientPortalRequest.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


async def get_request(db: AsyncSession, request_id: str, tenant_id: int):
    result = await db.execute(
        select(ClientPortalRequest)
        .options(selectinload(ClientPortalRequest.program))
        .where(
            ClientPortalRequest.id == request_id,
            ClientPortalRequest.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def update_status(
    db: AsyncSession,
    req: ClientPortalRequest,
    status: str,
    staff_reply: Optional[str],
    resolved_by_user_id: Optional[str],
):
    req.status = status
    if staff_reply is not None:
        req.staff_reply = staff_reply
    if status == "resolved":
        req.resolved_by_user_id = resolved_by_user_id
        req.resolved_at = datetime.utcnow()
    await db.commit()
    await db.refresh(req)
    return req
