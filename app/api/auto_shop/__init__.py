from fastapi import APIRouter
from . import admin_routes

router = APIRouter()
router.include_router(admin_routes.router, prefix="/admin", tags=["Auto Shop Admin"])

__all__ = ["router"]
