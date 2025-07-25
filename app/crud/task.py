from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.task import TaskTemplate, TaskItem, Task,TaskSubmission
from app.schemas.task import TaskTemplateCreate, TaskItemCreate, TaskCreate, TaskSubmissionCreate
import uuid
from datetime import datetime
from sqlalchemy import delete

# --------- Task Templates ---------
async def create_task_template(db: AsyncSession, template: TaskTemplateCreate):
    new_template = TaskTemplate(
        id=str(uuid.uuid4()),
        title=template.title,
        description=template.description
    )
    db.add(new_template)
    await db.flush()  # Get template ID before adding items

    for item in template.items or []:
        task_item = TaskItem(
            id=str(uuid.uuid4()),
            prompt=item.prompt,
            input_type=item.input_type,
            template_id=new_template.id
        )
        db.add(task_item)

    await db.commit()
    await db.refresh(new_template)
    return new_template


async def get_all_task_templates(db: AsyncSession):
    result = await db.execute(
        select(TaskTemplate).options(selectinload(TaskTemplate.items))
    )
    return result.scalars().all()


async def get_task_template(db: AsyncSession, template_id: str):
    result = await db.execute(
        select(TaskTemplate)
        .where(TaskTemplate.id == template_id)
        .options(selectinload(TaskTemplate.items))
    )
    return result.scalar_one_or_none()


# --------- Tasks (Assigned to Shifts) ---------
async def create_task(db: AsyncSession, task_data: TaskCreate):
    task = Task(
        id=str(uuid.uuid4()),
        shift_id=task_data.shift_id,
        template_id=task_data.template_id,
        is_completed=False,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def get_tasks_for_shift(db: AsyncSession, shift_id: str):
    result = await db.execute(
        select(Task)
        .where(Task.shift_id == shift_id)
        .options(selectinload(Task.template).selectinload(TaskTemplate.items))
    )
    return result.scalars().all()


# --------- Task Submissions ---------
async def submit_task_response(db: AsyncSession, submission_data: TaskSubmissionCreate):
    submission = TaskSubmission(
        id=str(uuid.uuid4()),
        task_id=submission_data.task_id,
        task_item_id=submission_data.task_item_id,
        worker_id=submission_data.worker_id,
        shift_id=submission_data.shift_id,
        response_text=submission_data.response_text,
        timestamp=datetime.utcnow(),
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)
    return submission

# --------- Task Delete ---------
async def delete_task_template(db: AsyncSession, template_id: str):
    await db.execute(delete(TaskItem).where(TaskItem.template_id == template_id))
    await db.execute(delete(TaskTemplate).where(TaskTemplate.id == template_id))
    await db.commit()