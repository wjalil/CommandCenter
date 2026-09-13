import secrets
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.models.catering.client_account import CateringClientAccount
from app.utils.auth import hash_secret, verify_secret

INVITE_TOKEN_TTL_HOURS = 72
RESET_TOKEN_TTL_HOURS = 2


async def get_by_program(db: AsyncSession, program_id: str, tenant_id: int):
    result = await db.execute(
        select(CateringClientAccount).where(
            CateringClientAccount.program_id == program_id,
            CateringClientAccount.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str, tenant_id: int):
    result = await db.execute(
        select(CateringClientAccount).where(
            CateringClientAccount.email == email.strip().lower(),
            CateringClientAccount.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, account_id: str):
    result = await db.execute(
        select(CateringClientAccount)
        .options(selectinload(CateringClientAccount.program))
        .where(CateringClientAccount.id == account_id)
    )
    return result.scalar_one_or_none()


async def get_by_invite_token(db: AsyncSession, token: str):
    result = await db.execute(
        select(CateringClientAccount)
        .options(selectinload(CateringClientAccount.program))
        .where(CateringClientAccount.invite_token == token)
    )
    account = result.scalar_one_or_none()
    if not account or not account.invite_token_expires_at:
        return None
    if account.invite_token_expires_at < datetime.utcnow():
        return None
    return account


async def get_by_reset_token(db: AsyncSession, token: str):
    result = await db.execute(
        select(CateringClientAccount)
        .options(selectinload(CateringClientAccount.program))
        .where(CateringClientAccount.reset_token == token)
    )
    account = result.scalar_one_or_none()
    if not account or not account.reset_token_expires_at:
        return None
    if account.reset_token_expires_at < datetime.utcnow():
        return None
    return account


async def create_or_resend_invite(db: AsyncSession, program_id: str, tenant_id: int, email: str):
    """Create the client account if needed, then (re)issue an invite token."""
    account = await get_by_program(db, program_id, tenant_id)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=INVITE_TOKEN_TTL_HOURS)

    if account:
        account.email = email.strip().lower()
        account.invite_token = token
        account.invite_token_expires_at = expires_at
        account.invite_sent_at = datetime.utcnow()
    else:
        account = CateringClientAccount(
            program_id=program_id,
            tenant_id=tenant_id,
            email=email.strip().lower(),
            invite_token=token,
            invite_token_expires_at=expires_at,
            invite_sent_at=datetime.utcnow(),
        )
        db.add(account)

    await db.commit()
    await db.refresh(account)
    return account


async def accept_invite(db: AsyncSession, account: CateringClientAccount, password: str):
    account.hashed_password = hash_secret(password)
    account.invite_token = None
    account.invite_token_expires_at = None
    account.is_active = True
    await db.commit()
    await db.refresh(account)
    return account


async def authenticate(db: AsyncSession, tenant_id: int, email: str, password: str):
    account = await get_by_email(db, email, tenant_id)
    if not account or not account.is_active or not account.hashed_password:
        return None
    if not verify_secret(password, account.hashed_password):
        return None
    account.last_login_at = datetime.utcnow()
    await db.commit()
    return account


async def start_password_reset(db: AsyncSession, tenant_id: int, email: str):
    account = await get_by_email(db, email, tenant_id)
    if not account or not account.is_active:
        return None
    account.reset_token = secrets.token_urlsafe(32)
    account.reset_token_expires_at = datetime.utcnow() + timedelta(hours=RESET_TOKEN_TTL_HOURS)
    await db.commit()
    await db.refresh(account)
    return account


async def complete_password_reset(db: AsyncSession, account: CateringClientAccount, password: str):
    account.hashed_password = hash_secret(password)
    account.reset_token = None
    account.reset_token_expires_at = None
    await db.commit()
    await db.refresh(account)
    return account
