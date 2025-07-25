### cookieops-backend/app/main.py

from fastapi import FastAPI,Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
import asyncio
from fastapi.staticfiles import StaticFiles
import os
from starlette.middleware.sessions import SessionMiddleware

from app.auth.routes import auth_backend, fastapi_users
from app.models.user import User
from app.api import shift_routes, task_routes, admin_routes, worker_routes,document_routes,public_routes
from app.db import create_db_and_tables
from app.schemas.user import UserRead, UserCreate
from app.models import shift, task, submission, user
from app.auth.routes import get_current_user
from app.api.custom_modules import inventory_routes, driver_order_routes,vending_form_route

# ⬇️ Make sure the 'static/uploads' folder exists (relative to project root)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
UPLOADS_DIR = os.path.join(STATIC_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)  # ⬅️ ensures directory exists

# Create the FastAPI app
app = FastAPI()

# ✅ Session middleware (required for PIN login sessions)
app.add_middleware(SessionMiddleware, secret_key="supersecret-cookieops-key")

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

# ✅ DB setup on startup
@app.on_event("startup")
def on_startup():
    print("🔧 Starting DB setup...")
    asyncio.create_task(create_db_and_tables())
    print("✅ DB setup launched (async)")

# ✅ Core app routers
app.include_router(shift_routes.router, prefix="/shifts")
app.include_router(task_routes.router, prefix="/tasks")
app.include_router(worker_routes.router)
app.include_router(document_routes.router, prefix="/documents")
app.include_router(public_routes.router)
app.include_router(inventory_routes.router)
app.include_router(driver_order_routes.router)
app.include_router(vending_form_route.router)
app.include_router(admin_routes.router) 