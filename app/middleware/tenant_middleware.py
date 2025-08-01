from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        user = request.scope.get("user", None)
        tenant_id = getattr(user, "tenant_id", 1) if user else 1
        request.state.tenant_id = tenant_id
        return await call_next(request)

