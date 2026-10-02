"""
Friday Payroll (admin) + Pay Stubs (workers).

Admin:  /admin/payroll — preview the week's finished, unpaid work, record the
        pay run, see who has signed for their pay, void a mistaken run.
Worker: /worker/pay — their pay stubs; each one is signed off ("I received
        $X") or disputed, with the time, IP and device recorded.
"""
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.models.payroll import PayRun, PayStub
from app.models.tenant import Tenant
from app.services import payroll as payroll_svc
from app.utils.business_time import WEEKDAYS, get_business_clock, parse_week_param, valid_tz

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ADMIN_ROLES = ("admin", "owner")
COMMON_TIMEZONES = [
    "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix",
    "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu",
]


def _is_admin(user) -> bool:
    return getattr(user, "role", None) in ADMIN_ROLES


def _back(path: str, **params) -> RedirectResponse:
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items() if v not in (None, ""))
    return RedirectResponse(f"{path}{'?' + query if query else ''}", status_code=303)


# ==================== admin ====================

@router.get("/admin/payroll")
async def admin_payroll(request: Request, week: Optional[str] = None,
                        db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if not _is_admin(user):
        return templates.TemplateResponse("unauthorized.html", {"request": request})
    clock = await get_business_clock(db, user.tenant_id)
    pay_week = parse_week_param(clock, week)
    this_week = clock.pay_week()
    preview = await payroll_svc.build_preview(db, user.tenant_id, clock, pay_week)
    runs = await payroll_svc.pay_runs(db, user.tenant_id)
    return templates.TemplateResponse("admin/payroll.html", {
        "request": request,
        "user": user,
        "clock": clock,
        "week": pay_week,
        "this_week": this_week,
        "is_future": pay_week.start > this_week.end,
        "preview": preview,
        "runs": runs,
        "payment_methods": payroll_svc.PAYMENT_METHODS,
        "timezones": COMMON_TIMEZONES,
        "weekdays": WEEKDAYS,
    })


@router.post("/admin/payroll/run")
async def admin_payroll_run(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if not _is_admin(user):
        return _back("/admin/payroll", error="Forbidden")
    form = await request.form()
    clock = await get_business_clock(db, user.tenant_id)
    pay_week = parse_week_param(clock, form.get("week"))
    if pay_week.start > clock.pay_week().end:
        return _back("/admin/payroll", week=pay_week.start.isoformat(), error="That pay week hasn't started yet.")
    user_ids = form.getlist("user_ids")
    if not user_ids:
        return _back("/admin/payroll", week=pay_week.start.isoformat(), error="Select at least one person to pay.")
    run = await payroll_svc.record_pay_run(
        db, user.tenant_id, clock, pay_week, paid_by_id=user.id, user_ids=user_ids,
        payment_method=form.get("payment_method"), notes=form.get("notes"),
    )
    if run is None:
        return _back("/admin/payroll", week=pay_week.start.isoformat(), error="Nothing left to pay for that week.")
    return _back(f"/admin/payroll/runs/{run.id}",
                 message=f"Paid {run.worker_count} worker(s) ${run.total_gross:,.2f}. Pay stubs sent for sign-off.")


@router.get("/admin/payroll/runs/{run_id}")
async def admin_payroll_run_detail(request: Request, run_id: str,
                                   db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if not _is_admin(user):
        return templates.TemplateResponse("unauthorized.html", {"request": request})
    run = (await db.execute(
        select(PayRun).where(PayRun.id == run_id, PayRun.tenant_id == user.tenant_id)
        .options(selectinload(PayRun.stubs), selectinload(PayRun.paid_by))
    )).scalar_one_or_none()
    if not run:
        return _back("/admin/payroll", error="Pay run not found")
    clock = await get_business_clock(db, user.tenant_id)
    stubs = sorted(run.stubs, key=lambda s: (s.worker_name or "").lower())
    return templates.TemplateResponse("admin/payroll_run.html", {
        "request": request, "user": user, "clock": clock, "run": run, "stubs": stubs,
        "can_void": not any(s.status == "acknowledged" for s in stubs),
    })


@router.post("/admin/payroll/runs/{run_id}/void")
async def admin_payroll_void(run_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if not _is_admin(user):
        return _back("/admin/payroll", error="Forbidden")
    run = (await db.execute(
        select(PayRun).where(PayRun.id == run_id, PayRun.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not run:
        return _back("/admin/payroll", error="Pay run not found")
    week = run.period_start.isoformat()
    if not await payroll_svc.void_pay_run(db, run):
        return _back(f"/admin/payroll/runs/{run_id}", error="Someone already signed for this pay run, so it can't be voided.")
    return _back("/admin/payroll", week=week, message="Pay run voided — that work is unpaid again.")


@router.post("/admin/payroll/stubs/{stub_id}/resolve")
async def admin_resolve_dispute(stub_id: str, resolution_note: str = Form(""),
                                db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if not _is_admin(user):
        return _back("/admin/payroll", error="Forbidden")
    stub = await db.get(PayStub, stub_id)
    if not stub or stub.tenant_id != user.tenant_id:
        return _back("/admin/payroll", error="Pay stub not found")
    stub.resolved_at = datetime.utcnow()
    stub.resolution_note = resolution_note.strip() or "Resolved"
    stub.status = "issued"  # back to the worker to sign
    await db.commit()
    return _back(f"/admin/payroll/runs/{stub.pay_run_id}", message="Marked resolved — sent back to the worker to sign.")


@router.post("/admin/payroll/settings")
async def admin_payroll_settings(timezone_name: str = Form(...), pay_week_end_weekday: int = Form(...),
                                 week: Optional[str] = Form(None),
                                 db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if not _is_admin(user):
        return _back("/admin/payroll", error="Forbidden")
    if not valid_tz(timezone_name) or not 0 <= pay_week_end_weekday <= 6:
        return _back("/admin/payroll", error="Invalid timezone or payday")
    tenant = await db.get(Tenant, user.tenant_id)
    tenant.timezone = timezone_name
    tenant.pay_week_end_weekday = pay_week_end_weekday
    await db.commit()
    return _back("/admin/payroll", message="Payroll settings saved.")


@router.get("/admin/payroll/stubs/{stub_id}")
async def admin_view_stub(request: Request, stub_id: str,
                          db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if not _is_admin(user):
        return templates.TemplateResponse("unauthorized.html", {"request": request})
    stub = (await db.execute(
        select(PayStub).where(PayStub.id == stub_id, PayStub.tenant_id == user.tenant_id)
        .options(selectinload(PayStub.pay_run))
    )).scalar_one_or_none()
    if not stub:
        return _back("/admin/payroll", error="Pay stub not found")
    clock = await get_business_clock(db, user.tenant_id)
    return templates.TemplateResponse("pay_stub.html", {
        "request": request, "user": user, "clock": clock, "stub": stub, "is_admin_view": True,
    })


# ==================== worker ====================

async def _own_stub(db: AsyncSession, user, stub_id: str) -> Optional[PayStub]:
    return (await db.execute(
        select(PayStub).where(PayStub.id == stub_id, PayStub.tenant_id == user.tenant_id, PayStub.user_id == user.id)
        .options(selectinload(PayStub.pay_run))
    )).scalar_one_or_none()


@router.get("/worker/pay")
async def worker_pay_list(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    clock = await get_business_clock(db, user.tenant_id)
    stubs = await payroll_svc.worker_stubs(db, user.tenant_id, user.id)
    return templates.TemplateResponse("worker_pay.html", {
        "request": request, "user": user, "clock": clock, "stubs": stubs,
    })


@router.get("/worker/pay/{stub_id}")
async def worker_pay_stub(request: Request, stub_id: str,
                          db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    stub = await _own_stub(db, user, stub_id)
    if not stub:
        return _back("/worker/pay")
    clock = await get_business_clock(db, user.tenant_id)
    return templates.TemplateResponse("pay_stub.html", {
        "request": request, "user": user, "clock": clock, "stub": stub, "is_admin_view": False,
    })


@router.post("/worker/pay/{stub_id}/acknowledge")
async def worker_acknowledge(request: Request, stub_id: str, signature_name: str = Form(""),
                             confirm: Optional[str] = Form(None),
                             db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    stub = await _own_stub(db, user, stub_id)
    if not stub:
        return _back("/worker/pay")
    if stub.status == "acknowledged":
        return _back(f"/worker/pay/{stub_id}")
    if not confirm or len(signature_name.strip()) < 2:
        return _back(f"/worker/pay/{stub_id}", error="Type your full name and tick the box to sign.")
    stub.status = "acknowledged"
    stub.signature_name = signature_name.strip()[:120]
    stub.acknowledged_at = datetime.utcnow()
    stub.ack_ip = request.client.host if request.client else None
    stub.ack_user_agent = (request.headers.get("user-agent") or "")[:300]
    await db.commit()
    return _back(f"/worker/pay/{stub_id}", message="Signed — thank you.")


@router.post("/worker/pay/{stub_id}/dispute")
async def worker_dispute(stub_id: str, dispute_note: str = Form(""),
                         db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    stub = await _own_stub(db, user, stub_id)
    if not stub:
        return _back("/worker/pay")
    if stub.status == "acknowledged":
        return _back(f"/worker/pay/{stub_id}", error="You already signed for this pay.")
    if len(dispute_note.strip()) < 3:
        return _back(f"/worker/pay/{stub_id}", error="Tell us what's wrong so we can fix it.")
    stub.status = "disputed"
    stub.dispute_note = dispute_note.strip()[:1000]
    stub.disputed_at = datetime.utcnow()
    await db.commit()
    return _back(f"/worker/pay/{stub_id}", message="Sent to the office — they'll follow up with you.")
