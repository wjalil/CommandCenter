from fastapi import APIRouter
from . import admin_routes, worker_routes

router = APIRouter()
router.include_router(admin_routes.router, prefix="/admin", tags=["Auto Shop Admin"])
router.include_router(worker_routes.router, prefix="/worker", tags=["Auto Shop Worker"])

__all__ = ["router"]
