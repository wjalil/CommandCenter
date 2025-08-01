from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.internal_task import InternalTask

async def get_all_tasks(db: AsyncSession):
    result = await db.execute(select(InternalTask))
    return result.scalars().all()

async def add_task(db: AsyncSession, title: str, tenant_id: int):
    task = InternalTask(title=title, tenant_id=tenant_id)
    db.add(task)
    await db.commit()

async def toggle_task(db: AsyncSession, task_id: str):
    task = await db.get(InternalTask, task_id)
    task.is_completed = not task.is_completed
    await db.commit()

async def delete_task(db: AsyncSession, task_id: str):
    task = await db.get(InternalTask, task_id)
    await db.delete(task)
    await db.commit()
