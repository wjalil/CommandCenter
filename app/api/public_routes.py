from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.customer.customer import Customer
from app.models.tenant import Tenant
from app.db import get_db
from app.models.user import User
from app.utils.auth import verify_secret

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


# ── Landing: workspace slug input ──────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def landing(request: Request, error: str = ""):
    return templates.TemplateResponse("landing.html", {"request": request, "error": error})


@router.get("/t/", response_class=HTMLResponse)
async def workspace_lookup(request: Request, slug: str = "", db: AsyncSession = Depends(get_db)):
    """Receives the workspace form submission and redirects to the tenant page."""
    slug = (slug or "").strip().lower()
    if not slug:
        return RedirectResponse("/?error=Please+enter+a+workspace+name", status_code=302)
    return RedirectResponse(f"/t/{slug}/", status_code=302)


# ── Per-tenant workspace landing ───────────────────────────────────────────
@router.get("/t/{slug}/", response_class=HTMLResponse)
async def workspace_landing(request: Request, slug: str, db: AsyncSession = Depends(get_db)):
    tenant = await _get_tenant_by_slug(slug, db)
    if not tenant:
        return templates.TemplateResponse(
            "landing.html",
            {"request": request, "error": f"Workspace '{slug}' not found. Check the name and try again."},
            status_code=404,
        )
    return templates.TemplateResponse("workspace_landing.html", {"request": request, "tenant": tenant})


# ── Worker & Customer PIN login ────────────────────────────────────────────
@router.get("/t/{slug}/login/{role}", response_class=HTMLResponse)
async def tenant_login_get(request: Request, slug: str, role: str, db: AsyncSession = Depends(get_db)):
    if role not in ("worker", "customer"):
        return RedirectResponse(f"/t/{slug}/", status_code=302)

    tenant = await _get_tenant_by_slug(slug, db)
    if not tenant:
        return RedirectResponse("/", status_code=302)

    return templates.TemplateResponse(
        "login_pin.html",
        {"request": request, "role": role, "tenant": tenant},
    )


@router.post("/t/{slug}/login/{role}", response_class=HTMLResponse)
async def tenant_login_post(
    request: Request,
    slug: str,
    role: str,
    pin_code: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if role not in ("worker", "customer"):
        return RedirectResponse(f"/t/{slug}/", status_code=302)

    tenant = await _get_tenant_by_slug(slug, db)
    if not tenant:
        return RedirectResponse("/", status_code=302)

    pin = (pin_code or "").strip()

    if role == "customer":
        result = await db.execute(
            select(Customer).where(Customer.tenant_id == tenant.id)
        )
        customers = result.scalars().all()
        customer = next((c for c in customers if verify_secret(pin, c.pin_code)), None)

        if customer:
            request.session["user_id"] = customer.id
            request.session["role"] = "customer"
            request.session["tenant_id"] = customer.tenant_id
            return RedirectResponse(url="/customer/", status_code=302)

    else:  # worker
        result = await db.execute(
            select(User).where(User.role == "worker", User.tenant_id == tenant.id)
        )
        workers = result.scalars().all()
        user = next((w for w in workers if verify_secret(pin, w.pin_code)), None)

        if user:
            request.session["user_id"] = user.id
            request.session["role"] = user.role
            request.session["tenant_id"] = user.tenant_id
            return RedirectResponse(url="/worker/home", status_code=302)

    return templates.TemplateResponse(
        "login_pin.html",
        {"request": request, "role": role, "tenant": tenant, "error": "Invalid PIN. Please try again."},
    )


# ── Admin email + password login ───────────────────────────────────────────
@router.get("/t/{slug}/admin/login", response_class=HTMLResponse)
async def admin_login_get(request: Request, slug: str, db: AsyncSession = Depends(get_db)):
    tenant = await _get_tenant_by_slug(slug, db)
    if not tenant:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login_admin.html", {"request": request, "tenant": tenant})


@router.post("/t/{slug}/admin/login", response_class=HTMLResponse)
async def admin_login_post(
    request: Request,
    slug: str,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _get_tenant_by_slug(slug, db)
    if not tenant:
        return RedirectResponse("/", status_code=302)

    result = await db.execute(
        select(User).where(
            User.email == email.strip().lower(),
            User.role.in_(["admin", "office_admin"]),
            User.tenant_id == tenant.id,
        )
    )
    user = result.scalars().first()

    if user and verify_secret(password, user.hashed_password):
        request.session["user_id"] = user.id
        request.session["role"] = user.role
        request.session["tenant_id"] = user.tenant_id
        # Office admins land on the auto shop dashboard, not the full admin panel
        landing = "/auto_shop/admin/" if user.role == "office_admin" else "/admin/dashboard"
        return RedirectResponse(url=landing, status_code=302)

    return templates.TemplateResponse(
        "login_admin.html",
        {
            "request": request,
            "tenant": tenant,
            "error": "Invalid email or password.",
            "prefill_email": email.strip(),
        },
    )


# ── Legacy routes: graceful redirect ──────────────────────────────────────
@router.get("/login/{role}", response_class=HTMLResponse)
async def legacy_login_redirect(request: Request, role: str):
    return templates.TemplateResponse(
        "landing.html",
        {
            "request": request,
            "error": "Please enter your workspace name to sign in.",
        },
    )


# ── Shared routes ──────────────────────────────────────────────────────────
@router.get("/home")
async def redirect_home(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    role = request.session.get("role")

    if not user_id or not role:
        return RedirectResponse(url="/", status_code=302)

    if role == "admin":
        return RedirectResponse(url="/admin/dashboard", status_code=302)
    if role == "office_admin":
        return RedirectResponse(url="/auto_shop/admin/", status_code=302)
    if role == "customer":
        return RedirectResponse(url="/customer/", status_code=302)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        return RedirectResponse(url="/worker/home", status_code=302)

    return RedirectResponse(url="/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


# ── Helper ─────────────────────────────────────────────────────────────────
async def _get_tenant_by_slug(slug: str, db: AsyncSession):
    result = await db.execute(select(Tenant).where(Tenant.slug == slug.lower()))
    return result.scalar_one_or_none()
