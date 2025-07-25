from fastapi import APIRouter, Depends, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.internal_task import InternalTask
from app.crud import internal_task

router = APIRouter(
    prefix="/admin",
    tags=["Internal Tasks"]
)

templates = Jinja2Templates(directory="app/templates")

# 📌 Create Task
@router.post("/internal-task")
async def create_internal_task(
    title: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    await internal_task.add_task(db, title)
    return RedirectResponse("/admin/dashboard", status_code=303)

# 🔁 Toggle Task Completion
@router.post("/internal-task/{task_id}/toggle")
async def toggle_internal_task(
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    try:
        await internal_task.toggle_task(db, task_id)
    except Exception as e:
        print(f"❌ Error toggling task {task_id}: {e}")
        await db.rollback()
    return RedirectResponse("/admin/dashboard", status_code=303)

# 🗑 Delete Task
@router.post("/internal-task/{task_id}/delete")
async def delete_internal_task(
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    await internal_task.delete_task(db, task_id)
    return RedirectResponse("/admin/dashboard", status_code=303)
