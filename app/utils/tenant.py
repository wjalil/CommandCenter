# app/utils/tenant.py
from fastapi import Request, HTTPException

def get_current_tenant_id(request: Request) -> int:
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Tenant not found in request.")
    try:
        return int(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Tenant ID must be an integer")
