from fastapi import APIRouter, Depends, Request, Form, Response, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from app.db import get_db
from app.auth.dependencies import get_current_user
from app.utils.timeclock_service import clock_in, clock_out, autoclose_stale_entries
from app.models.timeclock import TimeEntry, TimeStatus
from app.models.user import User

router = APIRouter()


# Worker view (one-button clock in/out)
@router.get("/worker/timeclock")
async def worker_timeclock_view(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
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
async def post_clock_in(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user), shift_id: str | None = Form(default=None)):
    e = await clock_in(db, user.tenant_id, user.id, shift_id, request.client.host if request.client else None, "web")
    await db.commit()
    return {"ok": True, "entry_id": e.id}


@router.post("/worker/clock-out")
async def post_clock_out(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    e = await clock_out(db, user.tenant_id, user.id, request.client.host if request.client else None, "web")
    await db.commit()
    return {"ok": True, "entry_id": e.id if e else None}


# Admin dashboard
@router.get("/admin/timeclock")
async def admin_timeclock_dashboard(
    request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user), page: int = 1, page_size: int = 100
):
    if user.role not in ("ADMIN", "OWNER"):
        raise HTTPException(status_code=403, detail="Forbidden")

    tenant_id = user.tenant_id
    offset = (page - 1) * page_size
    q = (
        select(
            TimeEntry.id,
            TimeEntry.user_id,
            TimeEntry.shift_id,
            TimeEntry.clock_in,
            TimeEntry.clock_out,
            TimeEntry.duration_minutes,
            TimeEntry.status,
            TimeEntry.hourly_rate,
            TimeEntry.gross_pay,
            User.hourly_rate.label("current_rate"),
        )
        .join(User, User.id == TimeEntry.user_id)
        .where(TimeEntry.tenant_id == tenant_id)
        .order_by(TimeEntry.clock_in.desc())
        .offset(offset)
        .limit(page_size)
    )

    res = await db.execute(q)
    rows = res.all()

    return request.app.state.templates.TemplateResponse(
        "admin/timeclock_dashboard.html",
        {"request": request, "rows": rows, "page": page, "page_size": page_size},
    )


@router.post("/admin/timeclock/{entry_id}/mark-paid")
async def admin_mark_paid(entry_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if user.role not in ("ADMIN", "OWNER"):
        raise HTTPException(status_code=403, detail="Forbidden")

    q = select(TimeEntry).where(and_(TimeEntry.id == entry_id, TimeEntry.tenant_id == user.tenant_id))
    res = await db.execute(q)
    e = res.scalars().first()
    if not e:
        return {"ok": False, "error": "Not found"}

    e.status = TimeStatus.PAID
    await db.commit()
    return {"ok": True}


@router.post("/admin/timeclock/autoclose-stale")
async def admin_autoclose_stale(db: AsyncSession = Depends(get_db), user=Depends(get_current_user), max_hours: int = 16):
    if user.role not in ("ADMIN", "OWNER"):
        raise HTTPException(status_code=403, detail="Forbidden")

    count = await autoclose_stale_entries(db, user.tenant_id, max_hours=max_hours)
    await db.commit()
    return {"ok": True, "closed_count": count}


@router.get("/admin/timeclock/export-weekly")
async def export_weekly(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user), week_start: str | None = None):
    if user.role not in ("ADMIN", "OWNER"):
        raise HTTPException(status_code=403, detail="Forbidden")

    from datetime import datetime, timedelta

    today = datetime.utcnow().date()
    start = datetime.fromisoformat(week_start).date() if week_start else today - timedelta(days=today.weekday())
    end = start + timedelta(days=7)

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
                TimeEntry.clock_in >= start,
                TimeEntry.clock_in < end,
            )
        )
        .group_by(TimeEntry.user_id)
    )
    res = await db.execute(q)
    rows = res.all()

    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["User ID", "Hours (decimal)", "Minutes", "Gross Pay($)"])
    for r in rows:
        mins = r.minutes or 0
        hours = round(mins / 60, 2)
        gross = round(float(r.gross or 0), 2)
        w.writerow([r.user_id, hours, mins, gross])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=timeclock_{start.isoformat()}.csv"},
    )
