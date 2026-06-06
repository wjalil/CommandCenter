from fastapi import APIRouter
from . import admin_routes
from . import driver_routes
from . import template_routes

router = APIRouter()

# Include admin routes
router.include_router(admin_routes.router, prefix="/admin", tags=["Delivery Admin"])

# Include driver routes
router.include_router(driver_routes.router, prefix="/driver", tags=["Delivery Driver"])

# Include template routes (also under /admin prefix)
router.include_router(template_routes.router, prefix="/admin", tags=["Delivery Templates"])

__all__ = ["router"]
