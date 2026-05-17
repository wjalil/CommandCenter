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
from app.models.tenant_module import TenantModule
from app.models.user import User
from app.auth.routes import get_current_user
from app.api.custom_modules import inventory_routes, driver_order_routes,vending_log_routes
from app.api.internal_task_routes import router as internal_task_router
from app.api.shopping_routes import router as shopping_router
from sqlalchemy.future import select
from sqlalchemy import text
from dotenv import load_dotenv
import app.models  # registers all models via models/__init__.py
from sqlalchemy.orm import configure_mappers
from app.utils.auth import hash_secret, is_hashed
configure_mappers()
from fastapi.staticfiles import StaticFiles
from app.api.admin import admin_timeclock_routes
from app.api.admin import schedule_grid_routes
from app.api.admin import admin_settings_routes
from app.api.admin import admin_customer_routes
from app.api import taskboard_routes
from app.api.catering import router as catering_router
from app.api.delivery import router as delivery_router
from app.api.auto_shop import router as auto_shop_router

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
# Security: httponly=True by default, https_only for HTTPS, same_site prevents CSRF
SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise ValueError("SESSION_SECRET environment variable is required! Generate with: openssl rand -hex 32")

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=3600,  # 1 hour session timeout
    same_site="lax",  # CSRF protection (strict would break OAuth flows)
    https_only=True,  # Only send over HTTPS in production
    # Note: httponly=True is the default in Starlette (cannot be disabled - good security!)
)

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

    # ── Schema migration: add new auth columns if missing ─────────────────────
    async with async_session() as db:
        for stmt in [
            "ALTER TABLE users ADD COLUMN email TEXT",
            "ALTER TABLE users ADD COLUMN hashed_password TEXT",
        ]:
            try:
                await db.execute(text(stmt))
                await db.commit()
            except Exception:
                pass  # Column already exists

    # ── Seed: Chai and Biscuit tenant ─────────────────────────────────────────
    async with async_session() as db:
        result = await db.execute(select(Tenant).where(Tenant.name == "Chai and Biscuit"))
        tenant = result.scalar_one_or_none()

        if not tenant:
            tenant = Tenant(name="Chai and Biscuit", slug="chai-and-biscuit")
            db.add(tenant)
            await db.commit()
            await db.refresh(tenant)
            print(f"🏢 Created tenant: {tenant.name}")
        else:
            if not tenant.slug:
                tenant.slug = "chai-and-biscuit"
                await db.commit()
            print(f"🏢 Tenant '{tenant.name}' already exists.")

        result = await db.execute(select(User).where(User.role == "admin", User.tenant_id == tenant.id))
        admin_count = len(result.scalars().all())

        if admin_count == 0:
            print("👤 No admin found. Creating default admin user...")
            admin = User(
                name="Admin",
                email="admin@chai-and-biscuit.local",
                pin_code=hash_secret("1234"),
                hashed_password=hash_secret("admin1234"),
                role="admin",
                is_active=True,
                tenant_id=tenant.id,
            )
            db.add(admin)
            await db.commit()
            print("✅ Default admin created (email: admin@chai-and-biscuit.local, password: admin1234).")
        else:
            print(f"🔐 {admin_count} admin(s) already exist. Skipping seed.")

    # ── Seed: Collision Kings (Auto Shop) tenant ───────────────────────────────
    async with async_session() as db:
        result = await db.execute(select(Tenant).where(Tenant.name == "Collision Kings"))
        auto_shop_tenant = result.scalar_one_or_none()

        if not auto_shop_tenant:
            auto_shop_tenant = Tenant(name="Collision Kings", slug="collision-kings")
            db.add(auto_shop_tenant)
            await db.commit()
            await db.refresh(auto_shop_tenant)
            print(f"🏢 Created tenant: {auto_shop_tenant.name}")
        else:
            if not auto_shop_tenant.slug:
                auto_shop_tenant.slug = "collision-kings"
                await db.commit()
            print(f"🏢 Tenant '{auto_shop_tenant.name}' already exists.")

        result = await db.execute(
            select(User).where(User.role == "admin", User.tenant_id == auto_shop_tenant.id)
        )
        admin_count = len(result.scalars().all())

        if admin_count == 0:
            auto_shop_admin = User(
                name="Shop Admin",
                email="admin@collision-kings.local",
                pin_code=hash_secret("5678"),
                hashed_password=hash_secret("admin5678"),
                role="admin",
                is_active=True,
                tenant_id=auto_shop_tenant.id,
            )
            db.add(auto_shop_admin)
            await db.commit()
            print("✅ Auto shop admin created (email: admin@collision-kings.local, password: admin5678).")
        else:
            print(f"🔐 {admin_count} admin(s) already exist for Collision Kings. Skipping seed.")

        # Seed module permissions for Collision Kings
        # Only auto_shop and core_ops (scheduling, timeclock, weekly hours) are enabled.
        collision_kings_modules = {
            "auto_shop": True,
            "core_ops": True,
            "weekly_hours": True,
            "catering": False,
            "catering_modules": False,
            "delivery": False,
            "driver_order": False,
            "customer_ordering": False,
            "taskboard": False,
            "shopping": False,
            "vending": False,
            "internal_tasks": False,
            "financial_summary": False,
            "invoices": False,
        }
        for module_key, enabled in collision_kings_modules.items():
            result = await db.execute(
                select(TenantModule).where(
                    TenantModule.tenant_id == auto_shop_tenant.id,
                    TenantModule.module_key == module_key,
                )
            )
            if not result.scalar_one_or_none():
                db.add(TenantModule(
                    tenant_id=auto_shop_tenant.id,
                    module_key=module_key,
                    enabled=enabled,
                ))
        await db.commit()
        print("✅ Module permissions seeded for Collision Kings.")

    # ── Migrate plaintext PINs and backfill missing passwords ─────────────────
    async with async_session() as db:
        from app.models.customer.customer import Customer as CustomerModel

        all_users_result = await db.execute(select(User))
        all_users = all_users_result.scalars().all()
        pin_count = pw_count = 0
        for u in all_users:
            changed = False
            original_pin = u.pin_code
            if not is_hashed(u.pin_code):
                u.pin_code = hash_secret(original_pin)
                changed = True
                pin_count += 1
            if u.role == "admin" and not u.hashed_password:
                u.hashed_password = hash_secret(f"admin{original_pin[:4]}")
                changed = True
                pw_count += 1
        if pin_count or pw_count:
            await db.commit()
            print(f"🔒 Hashed {pin_count} plaintext PIN(s), set {pw_count} missing admin password(s).")

        customer_result = await db.execute(select(CustomerModel))
        customers = customer_result.scalars().all()
        rehashed = 0
        for c in customers:
            if not is_hashed(c.pin_code):
                c.pin_code = hash_secret(c.pin_code)
                rehashed += 1
        if rehashed:
            await db.commit()
            print(f"🔒 Hashed {rehashed} plaintext customer PIN(s).")


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
app.include_router(catering_router, prefix="/catering")
app.include_router(delivery_router, prefix="/delivery")
app.include_router(auto_shop_router, prefix="/auto_shop")