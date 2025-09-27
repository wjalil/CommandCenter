from datetime import date, datetime, timedelta
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, func
from sqlalchemy.future import select

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.user import User
from app.models.shift import Shift

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday

@router.get("/shifts/clone")
async def clone_week_form(request: Request, user: User = Depends(get_current_admin_user)):
    return templates.TemplateResponse(
        "admin_shifts_clone.html",
        {"request": request, "user": user}
    )

@router.post("/shifts/clone")
async def clone_week(
    request: Request,
    source_week_start: date = Form(...),
    weeks_forward: int      = Form(1),
    filter_shift_type: Optional[str]      = Form(None),
    filter_label_contains: Optional[str]  = Form(None),
    keep_workers: Optional[str]           = Form(None),  # checkbox
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    try:
        start = week_start(source_week_start)
        end   = start + timedelta(days=7)

        q = select(Shift).where(
            and_(
                Shift.tenant_id == user.tenant_id,
                Shift.start_time >= datetime.combine(start, datetime.min.time()),
                Shift.start_time <  datetime.combine(end,   datetime.min.time()),
            )
        )
        if filter_shift_type:
            q = q.where(Shift.shift_type == filter_shift_type)
        if filter_label_contains:
            like = f"%{filter_label_contains}%"
            q = q.where(func.lower(Shift.label).like(func.lower(like)))

        result = await db.execute(q.order_by(Shift.start_time.asc()))
        src_shifts = result.scalars().all()

        total = 0
        for w in range(1, weeks_forward + 1):
            delta = timedelta(days=7 * w)
            for s in src_shifts:
                st = s.start_time + delta
                et = s.end_time + delta
                date_midnight = datetime(st.year, st.month, st.day, 0, 0, 0)

                cloned = Shift(
                    id=str(uuid.uuid4()),
                    label=s.label,
                    start_time=st,
                    end_time=et,
                    date=date_midnight,                # model uses DateTime
                    tenant_id=user.tenant_id,
                    is_filled=False,
                    is_completed=False,
                    is_recurring=False,                # deprecate recurring engine
                    shift_type=s.shift_type,
                    assigned_worker_id=(s.assigned_worker_id if keep_workers else None),
                    recurring_until=None,
                    is_seed=s.is_seed,
                    recurring_group_id=None,
                )
                db.add(cloned)
                total += 1

        await db.commit()
        return RedirectResponse(
            url=f"/admin/shifts/clone?success=Cloned%20{total}%20shift(s)!",
            status_code=303
        )
    except Exception:
        await db.rollback()
        return RedirectResponse(
            url="/admin/shifts/clone?error=Failed%20to%20clone%20week",
            status_code=303
        )
