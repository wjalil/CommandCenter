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

async def create_shift(db: AsyncSession, shift: ShiftCreate):
    new_shift = Shift(
        id=str(uuid.uuid4()),
        label=shift.label,
        start_time=shift.start_time,
        end_time=shift.end_time,
        is_recurring=shift.is_recurring or False,
        shift_type=shift.shift_type 
    )
    db.add(new_shift)
    await db.commit()
    await db.refresh(new_shift)

    # ✅ Auto-assign TaskTemplates with matching auto_assign_label
    result = await db.execute(
        select(TaskTemplate).where(TaskTemplate.auto_assign_label == new_shift.label)
    )
    matching_templates = result.scalars().all()

    for template in matching_templates:
        task = Task(
            shift_id=new_shift.id,
            template_id=template.id,
            is_completed=False
        )
        db.add(task)

    await db.commit()

    return new_shift

async def get_all_shifts(db: AsyncSession):
    result = await db.execute(
        select(Shift).options(
            selectinload(Shift.tasks).selectinload(Task.template),
        )
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

async def clone_next_week_recurring_shifts(db: AsyncSession):
    result = await db.execute(select(Shift).where(Shift.is_recurring == True))
    recurring_shifts = result.scalars().all()

    for shift in recurring_shifts:
        new_shift = Shift(
            id=str(uuid.uuid4()),
            label=shift.label,
            start_time=shift.start_time + timedelta(days=7),
            end_time=shift.end_time + timedelta(days=7),
            is_recurring=True,
            is_filled=False,
            is_completed=False,
            assigned_worker_id=None,
            shift_type=shift.shift_type  # ✅ preserve shift_type
        )
        db.add(new_shift)
        await db.flush()  # Ensure new_shift.id is usable for task assignment

        # ✅ Auto-assign TaskTemplates just like in create_shift
        task_templates_result = await db.execute(
            select(TaskTemplate).where(TaskTemplate.auto_assign_label == new_shift.label)
        )
        matching_templates = task_templates_result.scalars().all()

        for template in matching_templates:
            task = Task(
                shift_id=new_shift.id,
                template_id=template.id,
                is_completed=False
            )
            db.add(task)

    await db.commit()
