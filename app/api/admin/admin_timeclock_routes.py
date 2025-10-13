# app/api/admin_timeclock_routes.py

from __future__ import annotations
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Request, Query, Form
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, and_, func, update, or_, literal_column, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.auth.dependencies import get_current_user
from app.models.timeclock import TimeEntry, TimeStatus
from app.models.user import User
from app.utils.timeclock_service import autoclose_stale_entries

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# --- Helpers ---------------------------------------------------------------

def parse_date(s: Optional[str], default: Optional[datetime.date] = None):
    if s:
        return datetime.fromisoformat(s).date()
    return default

def week_bounds_utc(today_utc: datetime):
    d = today_utc.date()
    start = d - timedelta(days=d.weekday())        # Monday
    end = start + timedelta(days=7)
    return start, end

# --- Page: Admin Timeclock -------------------------------------------------

@router.get("/admin/timeclock")
async def admin_timeclock_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),

    # filters
    start: Optional[str] = Query(default=None),      # 'YYYY-MM-DD'
    end:   Optional[str] = Query(default=None),      # 'YYYY-MM-DD' (exclusive)
    status: Optional[str] = Query(default="all"),    # all|open|closed|approved|paid|unpaid
    q_user: Optional[str] = Query(default=None),     # user_id filter
):
    if user.role not in ("admin", "owner"):
        return templates.TemplateResponse("unauthorized.html", {"request": request})

    # Default to current week (UTC) if not provided
    now_utc = datetime.utcnow()
    def_start, def_end = week_bounds_utc(now_utc)

    s_date = parse_date(start, def_start)
    e_date = parse_date(end, def_end)

    # Base filter for range entries (only entries that started inside the range)
    range_filter = and_(
        TimeEntry.tenant_id == user.tenant_id,
        TimeEntry.clock_in >= s_date,
        TimeEntry.clock_in < e_date,
    )

    # Status filter
    status_filter = True
    if status == "open":
        status_filter = TimeEntry.status == TimeStatus.OPEN
    elif status == "closed":
        status_filter = TimeEntry.status == TimeStatus.CLOSED
    elif status == "approved":
        status_filter = TimeEntry.status == TimeStatus.APPROVED
    elif status == "paid":
        status_filter = TimeEntry.status == TimeStatus.PAID
    elif status == "unpaid":
        status_filter = TimeEntry.status.in_([TimeStatus.CLOSED, TimeStatus.APPROVED])

    # Optional user filter
    user_filter = True
    if q_user:
        user_filter = TimeEntry.user_id == q_user

    # --- KPI cards (range-scoped where applicable) ---
    # Total hours (closed/approved/paid only)
    kpi_hours_q = (
        select(func.coalesce(func.sum(TimeEntry.duration_minutes), 0))
        .where(range_filter)
        .where(TimeEntry.status.in_([TimeStatus.CLOSED, TimeStatus.APPROVED, TimeStatus.PAID]))
    )
    kpi_gross_q = (
        select(func.coalesce(func.sum(TimeEntry.gross_pay), 0))
        .where(range_filter)
        .where(TimeEntry.status.in_([TimeStatus.CLOSED, TimeStatus.APPROVED, TimeStatus.PAID]))
    )
    kpi_unpaid_q = (
        select(func.coalesce(func.sum(TimeEntry.gross_pay), 0))
        .where(range_filter)
        .where(TimeEntry.status.in_([TimeStatus.CLOSED, TimeStatus.APPROVED]))
    )
    # Open entries count (global for tenant, not range-scoped)
    kpi_open_q = (
        select(func.count())
        .where(TimeEntry.tenant_id == user.tenant_id)
        .where(TimeEntry.status == TimeStatus.OPEN)
    )

    hours_minutes = (await db.execute(kpi_hours_q)).scalar_one()
    gross_total   = (await db.execute(kpi_gross_q)).scalar_one()
    unpaid_total  = (await db.execute(kpi_unpaid_q)).scalar_one()
    open_count    = (await db.execute(kpi_open_q)).scalar_one()

    total_hours = round((hours_minutes or 0) / 60, 2)
    gross_total = float(gross_total or 0)
    unpaid_total = float(unpaid_total or 0)

    # --- Per-user aggregates (range + status + optional user) ---
    per_user_q = (
        select(
            User.id.label("user_id"),
            User.name.label("user_name"),
            func.coalesce(func.sum(TimeEntry.duration_minutes), 0).label("minutes"),
            func.coalesce(func.sum(TimeEntry.gross_pay), 0).label("gross"),
            # ✅ Use SQLAlchemy case(), not func.case()
            func.coalesce(
                func.sum(
                    case(
                        (TimeEntry.status.in_([TimeStatus.CLOSED, TimeStatus.APPROVED]), TimeEntry.gross_pay),
                        else_=0
                    )
                ),
                0
            ).label("unpaid_gross"),
            func.count(TimeEntry.id).label("entries"),
            func.max(TimeEntry.clock_in).label("last_clock_in")
        )
        .select_from(TimeEntry)
        .join(User, User.id == TimeEntry.user_id)
        .where(range_filter)
        .where(status_filter)
        .where(user_filter)
        .group_by(User.id, User.name)
        .order_by(func.lower(User.name))
    )

    per_user = (await db.execute(per_user_q)).all()

    # For user filter dropdown
    users_q = select(User.id, User.name).where(User.tenant_id == user.tenant_id).order_by(func.lower(User.name))
    users = (await db.execute(users_q)).all()

    ctx = {
        "request": request,
        "start": s_date.isoformat(),
        "end": e_date.isoformat(),
        "status": status,
        "q_user": q_user or "",
        "users": users,

        "kpi_total_hours": total_hours,
        "kpi_gross_total": f"{gross_total:,.2f}",
        "kpi_unpaid_total": f"{unpaid_total:,.2f}",
        "kpi_open_count": open_count,

        "rows": per_user,
    }
    return templates.TemplateResponse("admin/timeclock.html", ctx)

# --- Drawer data: worker entries in range ----------------------------------

@router.get("/admin/timeclock/entries")
async def admin_timeclock_entries(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
    user_id: str = Query(...),
    start: str = Query(...),
    end: str = Query(...),
    status: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
):
    if user.role not in ("admin", "owner"):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    s_date = datetime.fromisoformat(start).date()
    e_date = datetime.fromisoformat(end).date()

    base = and_(
        TimeEntry.tenant_id == user.tenant_id,
        TimeEntry.user_id == user_id,
        TimeEntry.clock_in >= s_date,
        TimeEntry.clock_in < e_date,
    )

    status_filter = True
    if status == "open":
        status_filter = TimeEntry.status == TimeStatus.OPEN
    elif status == "closed":
        status_filter = TimeEntry.status == TimeStatus.CLOSED
    elif status == "approved":
        status_filter = TimeEntry.status == TimeStatus.APPROVED
    elif status == "paid":
        status_filter = TimeEntry.status == TimeStatus.PAID
    elif status == "unpaid":
        status_filter = TimeEntry.status.in_([TimeStatus.CLOSED, TimeStatus.APPROVED])

    q = (
        select(
            TimeEntry.id,
            TimeEntry.clock_in,
            TimeEntry.clock_out,
            TimeEntry.duration_minutes,
            TimeEntry.hourly_rate,
            TimeEntry.gross_pay,
            TimeEntry.status,
            TimeEntry.notes
        )
        .where(base).where(status_filter)
        .order_by(TimeEntry.clock_in.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )

    rows = (await db.execute(q)).all()
    data = [
        {
            "id": r.id,
            "clock_in": (r.clock_in.isoformat() if r.clock_in else None),
            "clock_out": (r.clock_out.isoformat() if r.clock_out else None),
            "minutes": r.duration_minutes,
            "hourly_rate": float(r.hourly_rate or 0),
            "gross_pay": float(r.gross_pay or 0),
            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            "notes": r.notes or "",
        }
        for r in rows
    ]
    return JSONResponse({"entries": data})

# --- Bulk mark-paid for a set of users in range ----------------------------

@router.post("/admin/timeclock/mark-paid-bulk")
async def admin_timeclock_mark_paid_bulk(
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
    start: str = Form(...),
    end: str = Form(...),
    user_ids: str = Form(...),   # comma-separated list of user ids
):
    if user.role not in ("admin", "owner"):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    s_date = datetime.fromisoformat(start).date()
    e_date = datetime.fromisoformat(end).date()
    ids: List[str] = [x for x in (user_ids or "").split(",") if x]

    if not ids:
        return JSONResponse({"ok": True, "updated": 0})

    upd = (
        update(TimeEntry)
        .where(TimeEntry.tenant_id == user.tenant_id)
        .where(TimeEntry.user_id.in_(ids))
        .where(TimeEntry.clock_in >= s_date, TimeEntry.clock_in < e_date)
        .where(TimeEntry.status.in_([TimeStatus.CLOSED, TimeStatus.APPROVED]))
        .values(status=TimeStatus.PAID)
    )
    res = await db.execute(upd)
    await db.commit()
    # res.rowcount is not guaranteed on all backends, but on PG it is
    return JSONResponse({"ok": True, "updated": res.rowcount or 0})

# --- Autoclose stale -------------------------------------------------------

@router.post("/admin/timeclock/autoclose-stale")
async def admin_timeclock_autoclose_stale(
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
    max_hours: int = Form(16),
):
    if user.role not in ("admin", "owner"):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    count = await autoclose_stale_entries(db, user.tenant_id, max_hours=max_hours)
    await db.commit()
    return JSONResponse({"ok": True, "closed": count})

# --- Export summary CSV ----------------------------------------------------

@router.get("/admin/timeclock/export")
async def admin_timeclock_export(
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
    start: str = Query(...),
    end: str = Query(...),
    status: str = Query("all"),
):
    if user.role not in ("admin", "owner"):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    s_date = datetime.fromisoformat(start).date()
    e_date = datetime.fromisoformat(end).date()

    status_filter = True
    if status == "open":
        status_filter = TimeEntry.status == TimeStatus.OPEN
    elif status == "closed":
        status_filter = TimeEntry.status == TimeStatus.CLOSED
    elif status == "approved":
        status_filter = TimeEntry.status == TimeStatus.APPROVED
    elif status == "paid":
        status_filter = TimeEntry.status == TimeStatus.PAID
    elif status == "unpaid":
        status_filter = TimeEntry.status.in_([TimeStatus.CLOSED, TimeStatus.APPROVED])

    q = (
        select(
            User.id.label("user_id"),
            User.name.label("user_name"),
            func.coalesce(func.sum(TimeEntry.duration_minutes), 0).label("minutes"),
            func.coalesce(func.sum(TimeEntry.gross_pay), 0).label("gross"),
            func.count(TimeEntry.id).label("entries")
        )
        .select_from(TimeEntry)
        .join(User, User.id == TimeEntry.user_id)
        .where(TimeEntry.tenant_id == user.tenant_id)
        .where(TimeEntry.clock_in >= s_date, TimeEntry.clock_in < e_date)
        .where(status_filter)
        .group_by(User.id, User.name)
        .order_by(func.lower(User.name))
    )
    rows = (await db.execute(q)).all()

    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["User ID", "Name", "Hours (decimal)", "Minutes", "Gross ($)", "Entries"])
    for r in rows:
        mins = int(r.minutes or 0)
        hours = round(mins / 60, 2)
        gross = round(float(r.gross or 0), 2)
        w.writerow([r.user_id, r.user_name or "", hours, mins, gross, r.entries])

    fname = f"timeclock_summary_{s_date.isoformat()}_{e_date.isoformat()}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"}
    )


