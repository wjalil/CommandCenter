from fastapi import APIRouter, Depends, Request, Form, Response, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, case
from app.db import get_db
from app.auth.dependencies import get_current_user
from app.utils.timeclock_service import clock_in, clock_out, autoclose_stale_entries
from app.models.timeclock import TimeEntry, TimeStatus
from app.models.user import User

from datetime import datetime, date, timedelta
from typing import Optional, List
from app.utils.timezones import NY, week_bounds_utc_for_date, current_week_bounds_utc, ui_week_bounds_utc

router = APIRouter()

# -------------------------
# Worker view (one-button)
# -------------------------
@router.get("/worker/timeclock")
async def worker_timeclock_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    tenant_id = user.tenant_id
    q = select(TimeEntry).where(
        TimeEntry.user_id == user.id,
        TimeEntry.tenant_id == tenant_id,
        TimeEntry.status == TimeStatus.OPEN,
    )
    res = await db.execute(q)
    open_entry = res.scalars().first()

    return request.app.state.templates.TemplateResponse(
        "worker/timeclock.html",
        {"request": request, "user": user, "open_entry": open_entry},
    )

@router.post("/worker/clock-in")
async def post_clock_in(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    shift_id: Optional[str] = Form(default=None),
):
    e = await clock_in(
        db,
        user.tenant_id,
        user.id,
        shift_id,
        request.client.host if request.client else None,
        "web",
    )
    await db.commit()
    return {"ok": True, "entry_id": e.id}

@router.post("/worker/clock-out")
async def post_clock_out(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    e = await clock_out(
        db, user.tenant_id, user.id, request.client.host if request.client else None, "web"
    )
    await db.commit()
    return {"ok": True, "entry_id": e.id if e else None}

# -------------------------
# Admin: Dashboard (Mon→Mon ET, end-exclusive)
# Matches your template (start/end/status/q_user, rows, users, KPIs)
# -------------------------
@router.get("/admin/timeclock")
async def admin_timeclock_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    # paging (kept but we aggregate so not used by default)
    page: int = 1,
    page_size: int = 100,
    # filters
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    status: str = Query(default="all"),
    q_user: Optional[str] = Query(default=None),
    preset: Optional[str] = Query(default=None),  # "this_week" / "last_week"
):
    if user.role not in ("ADMIN", "OWNER"):
        raise HTTPException(status_code=403, detail="Forbidden")

    # --- Resolve time window (Mon 00:00 ET → next Mon 00:00 ET) ---
    if preset == "this_week":
        s_utc, e_utc = current_week_bounds_utc()
        s_local = s_utc.astimezone(NY)
        e_local = e_utc.astimezone(NY)
    elif preset == "last_week":
        this_s_utc, this_e_utc = current_week_bounds_utc()
        s_utc = this_s_utc - timedelta(days=7)
        e_utc = this_s_utc
        s_local = s_utc.astimezone(NY)
        e_local = e_utc.astimezone(NY)
    else:
        # Allow arbitrary UI-provided start/end (ET wall dates, end-exclusive)
        s_utc, e_utc, s_local, e_local = ui_week_bounds_utc(start, end)

    # For template inputs: pass ET wall dates as strings (YYYY-MM-DD)
    start_str = s_local.date().isoformat()
    end_str = e_local.date().isoformat()  # end-exclusive

    tenant_id = user.tenant_id

    # --- Optional status filter mapping ---
    # UI statuses: ['all','unpaid','closed','approved','paid','open']
    status_filter = None
    if status == "open":
        status_filter = [TimeStatus.OPEN]
    elif status == "closed":
        status_filter = [TimeStatus.CLOSED]
    elif status == "approved":
        status_filter = [TimeStatus.APPROVED]
    elif status == "paid":
        status_filter = [TimeStatus.PAID]
    elif status == "unpaid":
        # unpaid = everything not PAID within window
        status_filter = [TimeStatus.OPEN, TimeStatus.CLOSED, TimeStatus.APPROVED]

    # --- Users list for dropdown ---
    u_q = select(User.id, User.name).where(User.tenant_id == tenant_id).order_by(User.name.nulls_last())
    users_res = await db.execute(u_q)
    users = [{"id": uid, "name": uname} for uid, uname in users_res.all()]

    # --- Aggregation per user in window ---
    base_conds = [
        TimeEntry.tenant_id == tenant_id,
        TimeEntry.clock_in >= s_utc,
        TimeEntry.clock_in <  e_utc,
    ]
    if status_filter:
        base_conds.append(TimeEntry.status.in_(status_filter))
    if q_user:
        base_conds.append(TimeEntry.user_id == q_user)

    # Sum minutes, gross, unpaid_gross (gross where status != PAID), count entries, last clock_in
    unpaid_gross_case = case((TimeEntry.status != TimeStatus.PAID, TimeEntry.gross_pay), else_=0.0)

    agg_q = (
        select(
            TimeEntry.user_id.label("user_id"),
            func.coalesce(func.sum(TimeEntry.duration_minutes), 0).label("minutes"),
            func.coalesce(func.sum(TimeEntry.gross_pay), 0.0).label("gross"),
            func.coalesce(func.sum(unpaid_gross_case), 0.0).label("unpaid_gross"),
            func.count(TimeEntry.id).label("entries"),
            func.max(TimeEntry.clock_in).label("last_clock_in"),
            func.max(User.name).label("user_name"),
        )
        .join(User, User.id == TimeEntry.user_id)
        .where(and_(*base_conds))
        .group_by(TimeEntry.user_id)
        .order_by(func.max(TimeEntry.clock_in).desc().nulls_last())
    )

    agg_res = await db.execute(agg_q)
    rows = agg_res.all()

    # --- KPIs ---
    # total hours & gross/unpaid/open count in this window (ignores q_user/status to show the whole window KPIs)
    kpi_base_conds = [
        TimeEntry.tenant_id == tenant_id,
        TimeEntry.clock_in >= s_utc,
        TimeEntry.clock_in <  e_utc,
    ]
    kpi_q = select(
        func.coalesce(func.sum(TimeEntry.duration_minutes), 0).label("minutes"),
        func.coalesce(func.sum(TimeEntry.gross_pay), 0.0).label("gross"),
        func.coalesce(func.sum(case((TimeEntry.status != TimeStatus.PAID, TimeEntry.gross_pay), else_=0.0)), 0.0).label("unpaid"),
        func.coalesce(func.sum(case((TimeEntry.status == TimeStatus.OPEN, 1), else_=0)), 0).label("open_count")
    ).where(and_(*kpi_base_conds))

    kpi_res = await db.execute(kpi_q)
    kmins, kgross, kunpaid, kopen = kpi_res.first() or (0, 0.0, 0.0, 0)

    context = {
        "request": request,
        "rows": rows,
        "page": page,
        "page_size": page_size,
        "users": users,
        "q_user": q_user or "",
        "status": status,
        "start": start_str,   # ET wall date (YYYY-MM-DD), end-exclusive
        "end": end_str,       # ET wall date (YYYY-MM-DD), end-exclusive
        # KPIs formatted for template
        "kpi_total_hours": round((kmins or 0) / 60.0, 2),
        "kpi_gross_total": round(float(kgross or 0), 2),
        "kpi_unpaid_total": round(float(kunpaid or 0), 2),
        "kpi_open_count": int(kopen or 0),
    }

    return request.app.state.templates.TemplateResponse("admin/timeclock.html", context)
    # ^ ensure your template filename matches (you pasted the full template earlier).
    # If your file is "admin/timeclock_dashboard.html", change it here accordingly.

# -------------------------
# Bulk mark paid (used by the template)
# -------------------------
@router.post("/admin/timeclock/mark-paid-bulk")
async def admin_mark_paid_bulk(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    start: str = Form(...),  # ET YYYY-MM-DD
    end: str = Form(...),    # ET YYYY-MM-DD (end-exclusive)
    user_ids: str = Form(...),  # comma-separated
):
    if user.role not in ("ADMIN", "OWNER"):
        raise HTTPException(status_code=403, detail="Forbidden")

    s_utc, e_utc, _, _ = ui_week_bounds_utc(start, end)
    ids = [u.strip() for u in user_ids.split(",") if u.strip()]
    if not ids:
        return {"ok": False, "error": "No users selected"}

    q = select(TimeEntry).where(
        and_(
            TimeEntry.tenant_id == user.tenant_id,
            TimeEntry.user_id.in_(ids),
            TimeEntry.clock_in >= s_utc,
            TimeEntry.clock_in <  e_utc,
            TimeEntry.status.in_([TimeStatus.CLOSED, TimeStatus.APPROVED]),  # only close payable items
        )
    )
    res = await db.execute(q)
    entries = res.scalars().all()
    for e in entries:
        e.status = TimeStatus.PAID

    await db.commit()
    return {"ok": True, "updated": len(entries)}

# -------------------------
# Entries drawer JSON (used by the template)
# -------------------------
@router.get("/admin/timeclock/entries")
async def admin_timeclock_entries(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    user_id: str = Query(...),
    start: str = Query(...),  # ET YYYY-MM-DD
    end: str = Query(...),    # ET YYYY-MM-DD (end-exclusive)
    status: str = Query(default="all"),
):
    if user.role not in ("ADMIN", "OWNER"):
        raise HTTPException(status_code=403, detail="Forbidden")

    s_utc, e_utc, _, _ = ui_week_bounds_utc(start, end)

    conds = [
        TimeEntry.tenant_id == user.tenant_id,
        TimeEntry.user_id == user_id,
        TimeEntry.clock_in >= s_utc,
        TimeEntry.clock_in <  e_utc,
    ]
    if status == "open":
        conds.append(TimeEntry.status == TimeStatus.OPEN)
    elif status == "closed":
        conds.append(TimeEntry.status == TimeStatus.CLOSED)
    elif status == "approved":
        conds.append(TimeEntry.status == TimeStatus.APPROVED)
    elif status == "paid":
        conds.append(TimeEntry.status == TimeStatus.PAID)
    elif status == "unpaid":
        conds.append(TimeEntry.status.in_([TimeStatus.OPEN, TimeStatus.CLOSED, TimeStatus.APPROVED]))

    q = (
        select(
            TimeEntry.id,
            TimeEntry.clock_in,
            TimeEntry.clock_out,
            TimeEntry.duration_minutes,
            TimeEntry.hourly_rate,
            TimeEntry.gross_pay,
            TimeEntry.status,
            TimeEntry.notes,
        )
        .where(and_(*conds))
        .order_by(TimeEntry.clock_in.desc())
    )

    res = await db.execute(q)
    rows = res.all()

    # Serialize for the drawer card component (ISO with tz info if present)
    def _iso(dt):
        return dt.isoformat() if dt else None

    data = []
    for (
        _id,
        clock_in,
        clock_out,
        minutes,
        hourly_rate,
        gross_pay,
        status_val,
        notes,
    ) in rows:
        data.append(
            {
                "id": _id,
                "clock_in": _iso(clock_in),
                "clock_out": _iso(clock_out),
                "minutes": int(minutes or 0),
                "hourly_rate": float(hourly_rate or 0.0),
                "gross_pay": float(gross_pay or 0.0),
                "status": status_val,
                "notes": notes or "",
            }
        )

    return {"entries": data}

# -------------------------
# Admin: Autoclose stale
# -------------------------
@router.post("/admin/timeclock/autoclose-stale")
async def admin_autoclose_stale(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    max_hours: int = 16,
):
    if user.role not in ("ADMIN", "OWNER"):
        raise HTTPException(status_code=403, detail="Forbidden")

    count = await autoclose_stale_entries(db, user.tenant_id, max_hours=max_hours)
    await db.commit()
    return {"ok": True, "closed_count": count}

# -------------------------
# Admin: Export weekly (Mon→Mon ET, end-exclusive)
# -------------------------
@router.get("/admin/timeclock/export-weekly")
async def export_weekly(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    week_start: Optional[str] = None,
    week_end: Optional[str] = None,  # optional explicit end from picker
):
    if user.role not in ("ADMIN", "OWNER"):
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        start_utc, end_utc, start_local, end_local = ui_week_bounds_utc(week_start, week_end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date. Use YYYY-MM-DD.")

    # filename label: show Mon..Sun (end-exclusive so -1 day)
    label_start = start_local.date().isoformat()
    label_end = (end_local - timedelta(days=1)).date().isoformat()

    q = (
        select(
            TimeEntry.user_id.label("user_id"),
            func.sum(TimeEntry.duration_minutes).label("minutes"),
            func.sum(TimeEntry.gross_pay).label("gross"),
        )
        .where(
            and_(
                TimeEntry.tenant_id == user.tenant_id,
                TimeEntry.status.in_([TimeStatus.CLOSED, TimeStatus.APPROVED, TimeStatus.PAID]),
                TimeEntry.clock_in >= start_utc,
                TimeEntry.clock_in < end_utc,
            )
        )
        .group_by(TimeEntry.user_id)
    )
    res = await db.execute(q)
    rows = res.all()

    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["User ID", "Hours (decimal)", "Minutes", "Gross Pay ($)"])
    for r in rows:
        mins = int(r.minutes or 0)
        hours = round(mins / 60.0, 2)
        gross = round(float(r.gross or 0.0), 2)
        w.writerow([r.user_id, hours, mins, gross])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=timeclock_{label_start}_to_{label_end}.csv"
        },
    )
