# app/api/taskboard_routes.py
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from datetime import date, datetime
from typing import Optional

from app.db import get_db
from app.auth.dependencies import get_current_user
from app.models.taskboard import DailyTask
from app.utils.timezones import NY  # you already have this
from app.models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" in accept

# ---------- Admin: View Board (single-day) ----------


# ---------- Admin: View Board (single-day) ----------
@router.get("/admin/taskboard")
async def admin_taskboard_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    tenant_id = user.tenant_id

    # read day from query (or last sticky cookie), fallback to today
    qp_day = request.query_params.get("day") or request.cookies.get("admin_taskboard_day")
    try:
        the_day = date.fromisoformat(qp_day) if qp_day else date.today()
    except Exception:
        the_day = date.today()
    day_iso = the_day.isoformat()

    # filter by day and order like worker view
    res = await db.execute(
        select(DailyTask)
        .where(DailyTask.tenant_id == tenant_id, DailyTask.task_date == the_day)
        .order_by(DailyTask.order_index, DailyTask.created_at)
    )
    tasks = list(res.scalars())

    # preload names for completed_by_id to avoid lazy loading in template
    need_user_ids = {t.completed_by_id for t in tasks if getattr(t, "completed_by_id", None)}
    user_by_id = {}
    if need_user_ids:
        ures = await db.execute(select(User).where(User.id.in_(need_user_ids)))
        users = ures.scalars().all()
        user_by_id = {u.id: (u.name or str(u.id)[:8]) for u in users}

    resp = templates.TemplateResponse(
        "taskboard/admin_taskboard.html",
        {
            "request": request,
            "day": day_iso,           # <-- echoes selected day back to template
            "tasks": tasks,
            "user_by_id": user_by_id,
        },
    )
    # sticky for a week
    resp.set_cookie("admin_taskboard_day", day_iso, max_age=60*60*24*7, httponly=False)
    return resp


# ---------- Admin: Create Page ----------
@router.get("/admin/taskboard/create")
async def admin_task_create_view(
    request: Request,
    user=Depends(get_current_user),
):
    if user.role not in ("admin", "Owner"):
        raise HTTPException(status_code=403, detail="Not authorized")

    return templates.TemplateResponse(
        "taskboard/admin_task_create.html",
        {"request": request, "today_iso": date.today().isoformat()},
    )

# ---------- Admin: Create Task (form or JSON) ----------
@router.post("/admin/taskboard/create")
async def admin_create_task(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),

    title: str = Form(...),
    details: str = Form(""),

    task_date: Optional[str] = Form(None),
    day_of_week: Optional[int] = Form(None),
    shift_label: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    order_index: Optional[str] = Form(None),         # <-- str, not int

    # accept as str to tolerate ""
    target_qty: Optional[str] = Form(None),
    progress_qty: Optional[str] = Form(None),
    progress_note: Optional[str] = Form(None),
):
    if user.role not in ("admin", "Owner"):
        raise HTTPException(status_code=403, detail="Not authorized")

    tenant_id = user.tenant_id
    try:
        dt = date.fromisoformat(task_date) if task_date else None
    except Exception:
        dt = None

    def _to_int_or_none(v: Optional[str]):
        if v is None: return None
        v = v.strip()
        if v == "": return None
        try:
            return max(0, int(v))
        except ValueError:
            return None

    oi = _to_int_or_none(order_index) or 0
    tq = _to_int_or_none(target_qty)
    pq_raw = _to_int_or_none(progress_qty)
    note = (progress_note or "").strip() or None

    pq = min(pq_raw, tq) if (tq is not None and pq_raw is not None) else pq_raw

    new_task = DailyTask(
        tenant_id=tenant_id,
        title=title.strip(),
        details=(details.strip() or None),

        task_date=dt,
        day_of_week=day_of_week,
        shift_label=(shift_label or None),
        role=(role or None),
        order_index=oi,

        target_qty=tq,
        progress_qty=pq,
        progress_note=note,
    )
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)

    if _wants_json(request):
        return JSONResponse({"ok": True, "id": new_task.id})

    redirect_day = (dt or datetime.now(NY).date()).isoformat()
    return RedirectResponse(url=f"/admin/taskboard?day={redirect_day}", status_code=303)

# ---------- Admin: Delete Task (form or JSON) ----------
@router.post("/admin/taskboard/delete/{task_id}")
async def admin_delete_task(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    day: Optional[str] = None,
):
    if user.role not in ("admin", "Owner"):
        raise HTTPException(status_code=403, detail="Not authorized")

    tenant_id = user.tenant_id
    await db.execute(
        delete(DailyTask).where(DailyTask.id == task_id, DailyTask.tenant_id == tenant_id)
    )
    await db.commit()

    if _wants_json(request):
        return JSONResponse({"ok": True})

    redirect_day = day or datetime.now(NY).date().isoformat()
    return RedirectResponse(url=f"/admin/taskboard?day={redirect_day}", status_code=303)

# ---------- Toggle Complete (shared; fetch or form) ----------
@router.post("/taskboard/toggle/{task_id}")
async def toggle_task(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    day: Optional[str] = None,
):
    tenant_id = user.tenant_id
    task = (await db.execute(
        select(DailyTask).where(DailyTask.id == task_id, DailyTask.tenant_id == tenant_id)
    )).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    now = datetime.utcnow()
    if task.is_completed:
        task.is_completed = False
        task.completed_by_id = None
        task.completed_at = None
    else:
        task.is_completed = True
        task.completed_by_id = user.id  # NEW: record who
        task.completed_at = now
        # Optional nicety: if there is a target and progress is below target, snap to target
        if task.target_qty is not None and (task.progress_qty or 0) < task.target_qty:
            task.progress_qty = task.target_qty

    await db.commit()

    if _wants_json(request):
        return JSONResponse({"ok": True, "is_completed": task.is_completed})

    next_dest = request.query_params.get("next")
    if next_dest == "admin":
        redirect_day = (day or (task.task_date or datetime.now(NY).date()).isoformat())
        return RedirectResponse(url=f"/admin/taskboard?day={redirect_day}", status_code=303)
    else:
        return RedirectResponse(url="/worker/taskboard", status_code=303)

# ---------- Worker: Today’s View ----------
@router.get("/worker/taskboard")
async def worker_taskboard_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    tenant_id = user.tenant_id
    today = datetime.now(NY).date()

    q = select(DailyTask).where(
        DailyTask.tenant_id == tenant_id,
        DailyTask.task_date == today,
    ).order_by(DailyTask.order_index, DailyTask.created_at)

    # Optional: scope by worker's role
    if user.role not in ("admin", "Owner") and user.role:
        q = q.where((DailyTask.role == user.role) | (DailyTask.role.is_(None)))

    tasks = (await db.execute(q)).scalars().all()

    return templates.TemplateResponse(
        "taskboard/worker_taskboard.html",
        {"request": request, "tasks": tasks, "today": today.isoformat()},
    )

# ---------- Worker: Update progress (qty + note) ----------
@router.patch("/worker/taskboard/{task_id}/progress")
async def worker_update_task_progress(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),

    progress_qty: Optional[str] = Form(None),     # <-- str, not int
    progress_note: Optional[str] = Form(None),
):
    tenant_id = user.tenant_id

    task = (await db.execute(
        select(DailyTask).where(DailyTask.id == task_id, DailyTask.tenant_id == tenant_id)
    )).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    def _to_int_or_none(v: Optional[str]):
        if v is None: return None
        v = v.strip()
        if v == "": return None
        try:
            return max(0, int(v))
        except ValueError:
            return None

    pq_in = _to_int_or_none(progress_qty)
    if pq_in is not None:
        pq = pq_in
        if task.target_qty is not None:
            pq = min(pq, task.target_qty)
        task.progress_qty = pq

    if progress_note is not None:
        note = (progress_note or "").strip()
        task.progress_note = note or None

    task.updated_at = datetime.utcnow()
    await db.commit()

    return JSONResponse({
        "ok": True,
        "id": task.id,
        "progress_qty": task.progress_qty,
        "progress_note": task.progress_note
    })

# ---------- Admin: Quick edit of qty/note (optional convenience) ----------
@router.patch("/admin/taskboard/{task_id}/update")
async def admin_update_task_fields(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),

    # all optional; only provided fields update
    title: Optional[str] = Form(None),
    details: Optional[str] = Form(None),
    target_qty: Optional[str] = Form(None),     # <-- str
    progress_qty: Optional[str] = Form(None),   # <-- str
    progress_note: Optional[str] = Form(None),
    order_index: Optional[str] = Form(None),    # <-- str
    shift_label: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
):
    if user.role not in ("admin", "Owner"):
        raise HTTPException(status_code=403, detail="Not authorized")

    tenant_id = user.tenant_id
    task = (await db.execute(
        select(DailyTask).where(DailyTask.id == task_id, DailyTask.tenant_id == tenant_id)
    )).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    def _to_int_or_none(v: Optional[str]):
        if v is None: return None
        v = v.strip()
        if v == "": return None
        try:
            return max(0, int(v))
        except ValueError:
            return None

    if title is not None:
        task.title = title.strip() or task.title
    if details is not None:
        task.details = details.strip() or None
    if shift_label is not None:
        task.shift_label = shift_label.strip() or None
    if role is not None:
        task.role = role.strip() or None

    oi = _to_int_or_none(order_index)
    if oi is not None:
        task.order_index = oi

    # qty + note with guardrails
    if target_qty is not None:
        tq = _to_int_or_none(target_qty)
        task.target_qty = tq
        if tq is not None and task.progress_qty is not None and task.progress_qty > tq:
            task.progress_qty = tq

    if progress_qty is not None:
        pq = _to_int_or_none(progress_qty)
        if pq is None:
            task.progress_qty = None
        else:
            if task.target_qty is not None:
                pq = min(pq, task.target_qty)
            task.progress_qty = pq

    if progress_note is not None:
        note = (progress_note or "").strip()
        task.progress_note = note or None

    task.updated_at = datetime.utcnow()
    await db.commit()

    return JSONResponse({"ok": True, "id": task.id})
