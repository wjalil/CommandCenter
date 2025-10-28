# app/api/admin/shifts_bulk.py (POST)
# We are no longer using this
from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.templating import Jinja2Templates
from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.user import User
from app.schemas.shift import ShiftCreate
from app.crud import shift

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None

def parse_hhmm(s: Optional[str]) -> Optional[tuple]:
    # returns (hour, minute) or None
    if not s:
        return None
    try:
        h, m = s.split(":")
        return int(h), int(m)
    except Exception:
        return None

def truthy(s: Optional[str]) -> bool:
    return str(s).lower() in {"1", "true", "yes", "y", "on"}

@router.get("/shifts/bulk")
async def bulk_form(request: Request, user: User = Depends(get_current_admin_user)):
    return templates.TemplateResponse(
        "admin_shifts_bulk.html",
        {"request": request, "user": user}
    )


@router.post("/shifts/bulk")
async def bulk_create_shifts(
    request: Request,
    # 👇 alias to match your template names with [] 
    label: List[str]      = Form(..., alias="label[]"),
    date_raw: List[str]   = Form(..., alias="date[]"),         # strings, we'll parse
    start_raw: List[str]  = Form(..., alias="start_time[]"),   # "HH:MM"
    end_raw: List[str]    = Form(..., alias="end_time[]"),     # "HH:MM"
    stype: List[str]      = Form(..., alias="shift_type[]"),

    # Booleans/dates are optional & may be blank; accept as strings and parse
    rec_raw: Optional[List[str]]   = Form(None, alias="is_recurring[]"),
    until_raw: Optional[List[str]] = Form(None, alias="recurring_until[]"),
    seed_raw: Optional[List[str]]  = Form(None, alias="is_seed[]"),

    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    n = len(label)
    created, skipped = 0, 0

    # Normalize optional lists to length n
    def norm(arr, default=None):
        if arr is None:
            return [default] * n
        return (arr + [default] * n)[:n]

    rec_raw   = norm(rec_raw, None)
    until_raw = norm(until_raw, None)
    seed_raw  = norm(seed_raw, None)

    for i in range(n):
        lbl = (label[i] or "").strip()
        d   = parse_date(date_raw[i] if i < len(date_raw) else None)
        stp = parse_hhmm(start_raw[i] if i < len(start_raw) else None)
        etp = parse_hhmm(end_raw[i] if i < len(end_raw) else None)
        typ = (stype[i] or "").strip()

        # Skip incomplete/invalid rows gracefully (prevents 422)
        if not (lbl and d and stp and etp and typ):
            skipped += 1
            continue

        sh, sm = stp
        eh, em = etp
        st = datetime(d.year, d.month, d.day, sh, sm)
        et = datetime(d.year, d.month, d.day, eh, em)
        if et <= st:
            skipped += 1
            continue

        is_rec = truthy(rec_raw[i])
        ru_dt = None
        if is_rec:
            ru_d = parse_date(until_raw[i])
            if ru_d:
                ru_dt = datetime(ru_d.year, ru_d.month, ru_d.day, 0, 0, 0)

        payload = ShiftCreate(
            label=lbl,
            start_time=st,
            end_time=et,
            is_recurring=is_rec,
            shift_type=typ,
            tenant_id=str(user.tenant_id),   # schema expects str
            is_seed=truthy(seed_raw[i]) if seed_raw[i] is not None else True,
            recurring_until=ru_dt,
        )

        # Use your existing CRUD to preserve side-effects
        await shift.create_shift(db, payload, int(user.tenant_id))
        created += 1

    msg = f"Created {created} shift(s)."
    if skipped:
        msg += f" Skipped {skipped} row(s)."
    return RedirectResponse(
        url=f"/admin/shifts/bulk?success={msg.replace(' ','%20')}",
        status_code=303
    )
