from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.tenant_module import TenantModule

async def get_enabled_modules(db: AsyncSession, tenant_id: int) -> dict[str, bool]:
    res = await db.execute(
        select(TenantModule).where(TenantModule.tenant_id == tenant_id)
    )
    rows = res.scalars().all()
    return {r.module_key: bool(r.enabled) for r in rows}

def require_module(module_key: str):
    async def _dep(
        request: Request,
        db: AsyncSession = Depends(get_db),
        user=Depends(get_current_admin_user),
    ):
        tenant_id = user.tenant_id
        enabled = await get_enabled_modules(db, tenant_id)
        if not enabled.get(module_key, False):
            raise HTTPException(status_code=403, detail=f"Module disabled: {module_key}")
        request.state.enabled_modules = enabled
        return True
    return _dep
