# app/api/admin_timeclock_routes.py

from __future__ import annotations
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import uuid4
import logging
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Query, Form
from fastapi.responses import JSONResponse, Response, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, and_, func, update, or_, literal_column, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.auth.dependencies import get_current_user
from app.models.timeclock import TimeEntry, TimeStatus
from app.models.user import User
from app.utils.timeclock_service import autoclose_stale_entries, get_open_entry

log = logging.getLogger(__name__)

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

def et_to_utc(datetime_str: str) -> datetime:
    """Convert datetime-local string from ET to UTC datetime (naive, for DB storage)"""
    if not datetime_str:
        return None
    # Parse the datetime string (format: "YYYY-MM-DDTHH:MM" or "YYYY-MM-DDTHH:MM:SS")
    dt_naive = datetime.fromisoformat(datetime_str.replace("Z", ""))
    # Treat as ET timezone
    et_tz = ZoneInfo("America/New_York")
    dt_et = dt_naive.replace(tzinfo=et_tz)
    # Convert to UTC and remove timezone info (for naive datetime storage)
    dt_utc = dt_et.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return dt_utc

async def _check_overlap(
    db: AsyncSession,
    tenant_id: int,
    user_id: str,
    new_clock_in: datetime,
    new_clock_out: Optional[datetime],
    exclude_entry_id: Optional[str] = None
) -> Optional[TimeEntry]:
    """Check if new time range overlaps with existing entries for same user.

    Returns the overlapping TimeEntry if found, None otherwise.
    """

    # If no clock_out, can't determine overlap definitively (allow)
    if not new_clock_out:
        return None

    # Query for overlapping entries
    # Overlap logic: (A_start < B_end) AND (A_end > B_start)
    q = select(TimeEntry).where(
        TimeEntry.tenant_id == tenant_id,
        TimeEntry.user_id == user_id,
        TimeEntry.clock_in < new_clock_out,  # Existing start before new end
        or_(
            TimeEntry.clock_out.is_(None),  # OPEN entry (considered ongoing)
            TimeEntry.clock_out > new_clock_in  # Existing end after new start
        )
    )

    # Exclude the entry being edited
    if exclude_entry_id:
        q = q.where(TimeEntry.id != exclude_entry_id)

    result = await db.execute(q)
    overlapping = result.scalars().first()

    return overlapping

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
            TimeEntry.notes,
            TimeEntry.is_manual,
            TimeEntry.edited_by_id,
            TimeEntry.edited_at,
            TimeEntry.edit_reason,
            User.name.label("edited_by_name")
        )
        .outerjoin(User, User.id == TimeEntry.edited_by_id)
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
            "is_manual": r.is_manual or False,
            "edited_by_name": r.edited_by_name,
            "edited_at": r.edited_at.isoformat() if r.edited_at else None,
            "edit_reason": r.edit_reason or "",
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




# --- Edit Time Entry -------------------------------------------------------

@router.post("/admin/timeclock/entries/{entry_id}/edit")
async def admin_timeclock_edit_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
    clock_in: str = Form(...),
    clock_out: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    edit_reason: Optional[str] = Form(None),
    start: str = Form(...),
    end: str = Form(...),
):
    """Edit an existing time entry (admin only)"""
    if user.role not in ("admin", "owner"):
        return RedirectResponse(f"/admin/timeclock?error=Forbidden&start={start}&end={end}", status_code=303)

    # Fetch entry with tenant isolation
    q = select(TimeEntry).where(
        TimeEntry.id == entry_id,
        TimeEntry.tenant_id == user.tenant_id
    )
    result = await db.execute(q)
    entry = result.scalar_one_or_none()

    if not entry:
        return RedirectResponse(f"/admin/timeclock?error=Entry+not+found&start={start}&end={end}", status_code=303)

    # Prevent editing PAID entries
    if entry.status == TimeStatus.PAID:
        return RedirectResponse(f"/admin/timeclock?error=Cannot+edit+PAID+entries&start={start}&end={end}", status_code=303)

    # Parse and validate times (convert from ET to UTC)
    try:
        new_clock_in = et_to_utc(clock_in)
        new_clock_out = et_to_utc(clock_out) if clock_out else None
    except (ValueError, AttributeError):
        return RedirectResponse(f"/admin/timeclock?error=Invalid+datetime+format&start={start}&end={end}", status_code=303)

    # Validation: clock_out must be after clock_in
    if new_clock_out and new_clock_out <= new_clock_in:
        return RedirectResponse(f"/admin/timeclock?error=Clock+out+must+be+after+clock+in&start={start}&end={end}", status_code=303)

    # Validation: duration sanity check (warn if >16 hours)
    if new_clock_out:
        duration = (new_clock_out - new_clock_in).total_seconds() / 3600
        if duration > 16:
            log.warning(f"Admin {user.id} edited entry {entry_id} with duration {duration:.2f}h")

    # Validation: check for overlapping entries
    overlapping_entry = await _check_overlap(db, user.tenant_id, entry.user_id, new_clock_in, new_clock_out, exclude_entry_id=entry_id)
    if overlapping_entry:
        # Format times for error message
        overlap_in = overlapping_entry.clock_in.strftime("%Y-%m-%d %H:%M")
        overlap_out = overlapping_entry.clock_out.strftime("%Y-%m-%d %H:%M") if overlapping_entry.clock_out else "OPEN"
        error_msg = f"Overlapping+shift:+{overlap_in}+to+{overlap_out}+(entry+{overlapping_entry.id[:8]})"
        return RedirectResponse(f"/admin/timeclock?error={error_msg}&start={start}&end={end}", status_code=303)

    # Update entry
    old_clock_in = entry.clock_in
    old_clock_out = entry.clock_out

    entry.clock_in = new_clock_in
    entry.clock_out = new_clock_out
    entry.notes = notes
    entry.edited_by_id = user.id
    entry.edited_at = datetime.utcnow()
    entry.edit_reason = edit_reason

    # Recalculate financial fields if CLOSED/APPROVED/PAID
    if new_clock_out and entry.status != TimeStatus.OPEN:
        delta = new_clock_out - new_clock_in
        entry.duration_minutes = max(0, int(delta.total_seconds() // 60))
        # Keep original hourly_rate snapshot, recalculate gross_pay
        if entry.hourly_rate:
            entry.gross_pay = round((entry.duration_minutes / 60) * float(entry.hourly_rate), 2)

    # If changed from CLOSED to OPEN (cleared clock_out)
    if not new_clock_out and entry.status == TimeStatus.CLOSED:
        entry.status = TimeStatus.OPEN
        entry.duration_minutes = None
        entry.gross_pay = None

    await db.commit()

    log.info(f"Admin {user.id} edited entry {entry_id}: {old_clock_in} -> {new_clock_in}, {old_clock_out} -> {new_clock_out}")

    return RedirectResponse(f"/admin/timeclock?success=Entry+updated&start={start}&end={end}", status_code=303)


# --- Create Manual Entry ---------------------------------------------------

@router.post("/admin/timeclock/entries/create")
async def admin_timeclock_create_entry(
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
    user_id: str = Form(...),
    clock_in: str = Form(...),
    clock_out: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    start: str = Form(...),
    end: str = Form(...),
):
    """Create a manual time entry for a worker (admin only)"""
    if user.role not in ("admin", "owner"):
        return RedirectResponse(f"/admin/timeclock?error=Forbidden&start={start}&end={end}", status_code=303)

    # Validate worker exists in tenant
    worker_q = select(User).where(User.id == user_id, User.tenant_id == user.tenant_id)
    worker_result = await db.execute(worker_q)
    worker = worker_result.scalar_one_or_none()

    if not worker:
        return RedirectResponse(f"/admin/timeclock?error=Worker+not+found&start={start}&end={end}", status_code=303)

    # Parse times (convert from ET to UTC)
    try:
        new_clock_in = et_to_utc(clock_in)
        new_clock_out = et_to_utc(clock_out) if clock_out else None
    except (ValueError, AttributeError):
        return RedirectResponse(f"/admin/timeclock?error=Invalid+datetime+format&start={start}&end={end}", status_code=303)

    # Validation: clock_out must be after clock_in
    if new_clock_out and new_clock_out <= new_clock_in:
        return RedirectResponse(f"/admin/timeclock?error=Clock+out+must+be+after+clock+in&start={start}&end={end}", status_code=303)

    # Validation: overlap check
    overlapping_entry = await _check_overlap(db, user.tenant_id, user_id, new_clock_in, new_clock_out)
    if overlapping_entry:
        # Format times for error message
        overlap_in = overlapping_entry.clock_in.strftime("%Y-%m-%d %H:%M")
        overlap_out = overlapping_entry.clock_out.strftime("%Y-%m-%d %H:%M") if overlapping_entry.clock_out else "OPEN"
        error_msg = f"Overlapping+shift:+{overlap_in}+to+{overlap_out}+(entry+{overlapping_entry.id[:8]})"
        return RedirectResponse(f"/admin/timeclock?error={error_msg}&start={start}&end={end}", status_code=303)

    # Validation: if creating OPEN entry, ensure no existing OPEN entry for this worker
    if not new_clock_out:
        existing_open = await get_open_entry(db, user.tenant_id, user_id)
        if existing_open:
            return RedirectResponse(f"/admin/timeclock?error=Worker+already+has+OPEN+entry&start={start}&end={end}", status_code=303)

    # Create entry
    new_entry = TimeEntry(
        id=str(uuid4()),
        tenant_id=user.tenant_id,
        user_id=user_id,
        clock_in=new_clock_in,
        clock_out=new_clock_out,
        notes=notes,
        status=TimeStatus.OPEN if not new_clock_out else TimeStatus.CLOSED,
        clock_in_source="admin_manual",
        clock_out_source="admin_manual" if new_clock_out else None,
        is_manual=True,
        created_by_id=user.id,
    )

    # Calculate financial fields if CLOSED
    if new_clock_out:
        delta = new_clock_out - new_clock_in
        new_entry.duration_minutes = max(0, int(delta.total_seconds() // 60))
        new_entry.hourly_rate = worker.hourly_rate
        if worker.hourly_rate:
            new_entry.gross_pay = round((new_entry.duration_minutes / 60) * float(worker.hourly_rate), 2)

    db.add(new_entry)
    await db.commit()

    log.info(f"Admin {user.id} created manual entry {new_entry.id} for worker {user_id}")

    return RedirectResponse(f"/admin/timeclock?success=Manual+entry+created&start={start}&end={end}", status_code=303)


# --- Delete Time Entry -----------------------------------------------------

@router.delete("/admin/timeclock/entries/{entry_id}")
async def admin_timeclock_delete_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    """Delete a time entry (admin only, JSON response for AJAX)"""
    if user.role not in ("admin", "owner"):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    # Fetch entry with tenant isolation
    q = select(TimeEntry).where(
        TimeEntry.id == entry_id,
        TimeEntry.tenant_id == user.tenant_id
    )
    result = await db.execute(q)
    entry = result.scalar_one_or_none()

    if not entry:
        return JSONResponse({"error": "Entry not found"}, status_code=404)

    # Prevent deleting PAID entries
    if entry.status == TimeStatus.PAID:
        return JSONResponse({"error": "Cannot delete PAID entries"}, status_code=400)

    await db.delete(entry)
    await db.commit()

    log.info(f"Admin {user.id} deleted entry {entry_id}")

    return JSONResponse({"ok": True})
