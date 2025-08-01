from fastapi import APIRouter, Depends, Request, Form, Path, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from typing import List, Optional
from uuid import UUID
import shutil, os, uuid

from app.db import get_db
from app.schemas.task import TaskTemplateCreate, TaskCreate, TaskSubmissionCreate
from app.crud import task as task_crud
from app.crud import shift as shift_crud
from app.models.shift import Shift
from app.models.task import TaskSubmission, TaskTemplate, TaskItem, Task
from app.core.constants import UPLOAD_PATHS
from app.auth.dependencies import get_current_user
from app.utils.tenant import get_current_tenant_id

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = UPLOAD_PATHS['task_attachments']


# ---------- Admin: View & Create Templates ----------
@router.get("/admin/task-templates", name="view_task_templates")
async def view_task_templates(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    success: Optional[str] = None
):
    templates_list = await task_crud.get_all_task_templates(db, user.tenant_id)
    shifts = await shift_crud.get_all_shifts(db, user.tenant_id)
    return templates.TemplateResponse("admin_task_templates.html", {
        "request": request,
        "templates": templates_list,
        "shifts": shifts,
        "success": success
    })


@router.post("/admin/task-templates/create")
async def create_task_template(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    prompts: List[str] = Form(...),
    input_types: List[str] = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    items = [{"prompt": p, "input_type": t} for p, t in zip(prompts, input_types)]
    template_data = TaskTemplateCreate(
        title=title,
        description=description,
        items=items,
        tenant_id=user.tenant_id  # optional: could remove this if unused
    )
    await task_crud.create_task_template(db, template_data, tenant_id=user.tenant_id)  # ✅ Fix is here
    return RedirectResponse(
        url=str(request.url_for("view_task_templates")) + "?success=Template%20created%20successfully!",
        status_code=303,
    )


# ---------- Admin: Assign Template to Shift ----------
@router.post("/admin/tasks/assign")
async def assign_task_to_shift(
    shift_id: str = Form(...),
    template_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    await task_crud.create_task(db, TaskCreate(
        shift_id=shift_id,
        template_id=template_id,
        tenant_id=user.tenant_id)
        )
    return RedirectResponse(url="/admin/shifts", status_code=303)


# ---------- Worker: View Tasks for Shift ----------
@router.get("/shift/{shift_id}/tasks")
async def view_shift_tasks(
    shift_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    tasks = await task_crud.get_tasks_for_shift(db, shift_id, tenant_id=user.tenant_id)
    shift = await db.get(Shift, shift_id)

    if not shift or shift.tenant_id != user.tenant_id:
        return RedirectResponse(url="/", status_code=403)

    submission_result = await db.execute(
        select(TaskSubmission.task_item_id)
        .where(TaskSubmission.shift_id == shift_id)
    )
    submitted_items = {row[0] for row in submission_result.all()}

    return templates.TemplateResponse("shift_task_checklist.html", {
        "request": request,
        "tasks": tasks,
        "shift_id": shift_id,
        "shift": shift,
        "submitted_items": submitted_items,
        "worker_id": shift.assigned_worker_id
    })


# ---------- Worker: Submit Task Response ----------
@router.post("/submit")
async def submit_task_response(
    request: Request,
    task_id: str = Form(...),
    task_item_id: str = Form(...),
    worker_id: str = Form(...),
    shift_id: str = Form(...),
    response_text: str = Form(...),
    photo: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    filename = None
    if photo and photo.filename:
        filename = f"{uuid.uuid4()}_{photo.filename}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)

    submission = TaskSubmissionCreate(
        task_id=task_id,
        task_item_id=task_item_id,
        worker_id=worker_id,
        shift_id=shift_id,
        response_text=response_text,
        photo_filename=filename,
        tenant_id=user.tenant_id  # ✅ Scoping here
    )
    await task_crud.submit_task_response(db, submission)
    return RedirectResponse(url=f"/tasks/shift/{shift_id}/tasks?success=1", status_code=303)


# ---------- Admin: Delete Task Template ----------
@router.post("/admin/task-templates/{template_id}/delete")
async def delete_task_template(
    template_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    await task_crud.delete_task_template(db, template_id, user.tenant_id)
    return RedirectResponse(url="/tasks/admin/task-templates", status_code=303)


# ---------- Admin: Update Task Template ----------
@router.post("/admin/task-templates/{template_id}/update")
async def update_task_template(
    request: Request,
    template_id: UUID,
    title: str = Form(...),
    description: str = Form(""),
    auto_assign_label: str = Form(None),
    prompts: List[str] = Form(...),
    input_types: List[str] = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if len(prompts) != len(input_types):
        return RedirectResponse(
            url=str(request.url_for("view_task_templates")) + "?success=Mismatch%20in%20prompts%20and%20types",
            status_code=303
        )

    template = await db.get(TaskTemplate, str(template_id))
    if not template or template.tenant_id != user.tenant_id:
        return RedirectResponse(
            url=str(request.url_for("view_task_templates")) + "?success=Template%20not%20found",
            status_code=303
        )

    template.title = title
    template.description = description
    template.auto_assign_label = auto_assign_label.strip() if auto_assign_label else None

    await db.execute(delete(TaskItem).where(TaskItem.template_id == str(template_id)))

    for prompt, input_type in zip(prompts, input_types):
        item = TaskItem(template_id=str(template_id), prompt=prompt, input_type=input_type)
        db.add(item)

    await db.commit()

    return RedirectResponse(
        url=str(request.url_for("view_task_templates")) + "?success=Template%20updated%20successfully!",
        status_code=303
    )


# ---------- Admin: View All Task Submissions ----------
@router.get("/admin/task-submissions")
async def view_task_submissions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    result = await db.execute(
        select(TaskSubmission)
        .where(TaskSubmission.tenant_id == user.tenant_id)
        .options(
            selectinload(TaskSubmission.shift).selectinload(Shift.worker),
            selectinload(TaskSubmission.task).selectinload(Task.template),
            selectinload(TaskSubmission.task_item)
        )
    )
    submissions = result.scalars().all()

    return templates.TemplateResponse("admin_task_submissions.html", {
        "request": request,
        "submissions": submissions
    })
