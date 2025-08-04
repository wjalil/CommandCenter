from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
from app.models.shift import Shift
from app.schemas.shift import ShiftCreate
from app.models.task import Task, TaskTemplate
import uuid
from datetime import timedelta
from sqlalchemy.orm import selectinload
from fastapi import HTTPException

async def create_shift(db: AsyncSession, shift: ShiftCreate, tenant_id: int):
    new_shift = Shift(
        id=str(uuid.uuid4()),
        label=shift.label,
        start_time=shift.start_time,
        end_time=shift.end_time,
        is_recurring=shift.is_recurring or False,
        shift_type=shift.shift_type,
        tenant_id=tenant_id,
        is_seed=shift.is_seed,  # ✅ Add this
        recurring_until=shift.recurring_until,  # ✅ Add this
        recurring_group_id=shift.recurring_group_id,  # optional, if you're supporting it
    )
    db.add(new_shift)
    await db.commit()
    await db.refresh(new_shift)

    # ✅ Auto-assign TaskTemplates with matching auto_assign_label scoped by tenant
    result = await db.execute(
        select(TaskTemplate).where(
            TaskTemplate.auto_assign_label == new_shift.label,
            TaskTemplate.tenant_id == tenant_id
        )
    )
    matching_templates = result.scalars().all()

    for template in matching_templates:
        task = Task(
            shift_id=new_shift.id,
            template_id=template.id,
            is_completed=False,
            tenant_id=tenant_id
        )
        db.add(task)

    await db.commit()
    return new_shift

async def get_all_shifts(db: AsyncSession, tenant_id: int):
    result = await db.execute(
        select(Shift)
        .where(Shift.tenant_id == tenant_id)
        .options(selectinload(Shift.tasks).selectinload(Task.template))
    )
    return result.scalars().all()

async def claim_shift(db: AsyncSession, shift_id: str, user_id: str):
    stmt = (
        update(Shift)
        .where(Shift.id == shift_id, Shift.is_filled == False)
        .values(assigned_worker_id=user_id, is_filled=True)
        .execution_options(synchronize_session="fetch")
    )
    await db.execute(stmt)
    await db.commit()

async def update_shift(db: AsyncSession, shift_id: str, updates: dict):
    stmt = (
        update(Shift)
        .where(Shift.id == shift_id)
        .values(**updates)
        .execution_options(synchronize_session="fetch")
    )
    await db.execute(stmt)
    await db.commit()

async def delete_shift(db: AsyncSession, shift_id: str):
    result = await db.execute(select(Shift).where(Shift.id == shift_id))
    shift = result.scalar_one_or_none()

    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")

    # This will orphan tasks — shift_id will be set to NULL due to ondelete="SET NULL"
    await db.delete(shift)
    await db.commit()

async def unclaim_shift(db: AsyncSession, shift_id: str):
    stmt = (
        update(Shift)
        .where(Shift.id == shift_id)
        .values(assigned_worker_id=None, is_filled=False)
        .execution_options(synchronize_session="fetch")
    )
    await db.execute(stmt)
    await db.commit()

async def mark_shift_complete(db: AsyncSession, shift_id: str):
    stmt = (
        update(Shift)
        .where(Shift.id == shift_id)
        .values(is_completed=True)
        .execution_options(synchronize_session="fetch")
    )
    await db.execute(stmt)
    await db.commit()

async def clone_next_week_recurring_shifts(db: AsyncSession, tenant_id: int):
    # ✅ Only clone from active recurring SEED shifts for this tenant
    result = await db.execute(
        select(Shift).where(
            Shift.is_recurring == True,
            Shift.is_seed == True,
            Shift.tenant_id == tenant_id
        )
    )
    recurring_shifts = result.scalars().all()

    for shift in recurring_shifts:
        next_start = shift.start_time + timedelta(days=7)
        next_end = shift.end_time + timedelta(days=7)

        # ✅ Prevent infinite clones past cutoff
        if shift.recurring_until and next_start > shift.recurring_until:
            continue

        # ✅ Clone the shift (preserves ALL original fields)
        new_shift = Shift(
            id=str(uuid.uuid4()),
            label=shift.label,
            start_time=next_start,
            end_time=next_end,
            is_recurring=True,
            is_seed=False,  # ✅ critical: don't use this as future seed
            recurring_until=shift.recurring_until,  # ✅ propagate
            recurring_group_id=shift.recurring_group_id,
            is_filled=False,
            is_completed=False,
            assigned_worker_id=None,
            shift_type=shift.shift_type,
            tenant_id=tenant_id
        )
        db.add(new_shift)
        await db.flush()

        # ✅ Attach any matching TaskTemplates (no logic changed)
        task_templates_result = await db.execute(
            select(TaskTemplate).where(
                TaskTemplate.auto_assign_label == new_shift.label,
                TaskTemplate.tenant_id == tenant_id
            )
        )
        matching_templates = task_templates_result.scalars().all()

        for template in matching_templates:
            task = Task(
                shift_id=new_shift.id,
                template_id=template.id,
                is_completed=False,
                tenant_id=tenant_id
            )
            db.add(task)

    await db.commit()


