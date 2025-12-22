### cookieops-backend/app/main.py
from fastapi import FastAPI,Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
import asyncio
from fastapi.staticfiles import StaticFiles
from app.middleware.tenant_middleware import TenantMiddleware
from fastapi.middleware import Middleware
import os
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from app.auth.routes import auth_backend, fastapi_users
from app.models.user import User
from app.api import shift_routes, task_routes, admin_routes, worker_routes,document_routes,public_routes,customer_routes
from app.api.menu_routes import admin_menu_routes, admin_menu_item_routes
from app.api.shortage_log_routes import router as shortage_router
from app.db import create_db_and_tables,async_session
from app.schemas.user import UserRead, UserCreate
from app.models import shift, task, submission, user
from app.models.tenant import Tenant
from app.models.user import User
from app.auth.routes import get_current_user
from app.api.custom_modules import inventory_routes, driver_order_routes,vending_log_routes
from app.api.internal_task_routes import router as internal_task_router
from app.api.shopping_routes import router as shopping_router
from sqlalchemy.future import select
from dotenv import load_dotenv
import app.models  # registers all models via models/__init__.py
from sqlalchemy.orm import configure_mappers
configure_mappers()
from fastapi.staticfiles import StaticFiles
from app.api.admin import admin_timeclock_routes
from app.api.admin import schedule_grid_routes
from app.api.admin import admin_settings_routes
from app.api.admin import admin_customer_routes
from app.api import taskboard_routes

load_dotenv()

# ⬇️ New correct static directory
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
UPLOADS_DIR = os.path.join(STATIC_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        user = request.scope.get("user")

        # Fallback to default tenant for now
        tenant_id = getattr(user, "tenant_id", 1) if user else 1

        request.state.tenant_id = tenant_id
        return await call_next(request)


# Create the FastAPI app
app = FastAPI()


# ✅ Session middleware (required for PIN login sessions)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "fallback-secret"))

# ✅ Tenant middleware (injects request.state.tenant_id)
app.add_middleware(TenantMiddleware)

# ✅ Mount static files (e.g., for uploaded docs)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ✅ Swagger Bearer token support for "Authorize" button
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="CookieOps API",
        version="1.0.0",
        description="API for managing cookie biz shifts, tasks, and users.",
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT"
        }
    }
    for path in openapi_schema["paths"].values():
        for operation in path.values():
            operation["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# ✅ Auth routes
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"]
)

app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth/users",
    tags=["auth"]
)

app.include_router(admin_routes.router)

app.include_router(
    fastapi_users.get_users_router(UserRead, UserCreate),
    prefix="/auth/users",
    tags=["auth"]
)

# ✅ Allow frontend dev (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In prod, restrict this!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/whoami")
async def whoami(user=Depends(get_current_user)):
    print("✅ User Authenticated:", user)
    return user

@app.on_event("startup")
async def on_startup():
    print("🔧 Starting DB setup...")
    await create_db_and_tables()
    print("✅ DB schema created.")
    # ⬇️ Seed default tenant if it doesn't exist
    async with async_session() as db:
        result = await db.execute(select(Tenant).where(Tenant.name == "Chai and Biscuit"))
        tenant = result.scalar_one_or_none()

        if not tenant:
            tenant = Tenant(name="Chai and Biscuit")
            db.add(tenant)
            await db.commit()
            print(f"🏢 Created tenant: {tenant.name}")
        else:
            print(f"🏢 Tenant '{tenant.name}' already exists.")

    
        result = await db.execute(select(User).where(User.role == "admin"))
        existing_admin = result.scalars().first()

        if not existing_admin:
            print("👤 No admin found. Creating default admin user...")
            admin = User(
                name="Admin",
                pin_code="1234",
                role="admin",
                is_active=True,
                tenant_id=tenant.id 
            )
            db.add(admin)
            await db.commit()
            print("✅ Default admin created.")
        else:
            print("🔐 Admin already exists. No seed needed.")


# ✅ Core app routers
app.include_router(shift_routes.router, prefix="/shifts")
app.include_router(task_routes.router, prefix="/tasks")
app.include_router(worker_routes.router)
app.include_router(document_routes.router, prefix="/documents")
app.include_router(public_routes.router)
app.include_router(inventory_routes.router)
app.include_router(driver_order_routes.router)
app.include_router(vending_log_routes.router)
app.include_router(internal_task_router)
app.include_router(admin_routes.router)
app.include_router(shortage_router)
app.include_router(admin_menu_routes.router)
app.include_router(admin_menu_item_routes.router)
app.include_router(customer_routes.router)
app.include_router(shopping_router)
app.include_router(admin_timeclock_routes.router)
app.include_router(schedule_grid_routes.router)
app.include_router(admin_settings_routes.router)
app.include_router(admin_customer_routes.router)
app.include_router(taskboard_routes.router)