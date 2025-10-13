from fastapi import APIRouter, Request, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.db import get_db
from app.models.document import Document
import uuid
import os
import shutil
from app.core.constants import UPLOAD_PATHS
from app.utils.tenant import get_current_tenant_id  # ✅ New helper import
from uuid import UUID
from pathlib import Path

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
UPLOAD_DIR = UPLOAD_PATHS['documents']

# ---------- Admin: View All Uploaded Documents ----------
@router.get("/admin/documents", name="view_documents")
async def view_documents(
    request: Request,
    search: str = "",
    db: AsyncSession = Depends(get_db)
):
    tenant_id = get_current_tenant_id(request)

    stmt = select(Document).where(Document.tenant_id == tenant_id)
    if search:
        stmt = stmt.where(Document.title.ilike(f"%{search}%"))

    result = await db.execute(stmt)
    documents = result.scalars().all()

    return templates.TemplateResponse("admin_documents.html", {
        "request": request,
        "documents": documents,
        "search_query": search,
    })


# ---------- Admin: Upload a New Document ----------
@router.post("/admin/documents/upload")
async def upload_document(
    request: Request,
    title: str = Form(...),
    tags: str = Form(""),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    tenant_id = get_current_tenant_id(request)

    # Generate safe filename
    original_filename = file.filename
    extension = os.path.splitext(original_filename)[1]
    new_filename = f"{uuid.uuid4()}{extension}"
    file_path = os.path.join(UPLOAD_DIR, new_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    doc = Document(
        title=title,
        filename=new_filename,
        original_filename=original_filename,
        tags=tags,
        tenant_id=tenant_id  # ✅ Assign to current tenant
    )
    db.add(doc)
    await db.commit()

    return RedirectResponse(
        url=str(request.url_for("view_documents")) + "?success=Upload%20successful",
        status_code=303
    )


# ---------- Worker: View Documents ----------
@router.get("/worker/documents")
async def worker_documents_view(
    request: Request,
    search: str = "",
    db: AsyncSession = Depends(get_db)
):
    tenant_id = get_current_tenant_id(request)

    stmt = select(Document).where(Document.tenant_id == tenant_id)
    if search:
        stmt = stmt.where(Document.title.ilike(f"%{search}%"))

    result = await db.execute(stmt)
    documents = result.scalars().all()

    return templates.TemplateResponse("worker_documents.html", {
        "request": request,
        "documents": documents,
        "search_query": search,
    })


@router.post("/admin/documents/delete/{doc_id}")
async def delete_document(
    doc_id: str,  # accept as string so we control validation
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = get_current_tenant_id(request)

    # Validate UUID (returns 422 if not valid)
    try:
        doc_uuid = UUID(doc_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid document id")

    # If your Document.id column is String, compare to str(uuid);
    # If it's a UUID column, compare directly with doc_uuid.
    stmt = select(Document).where(
        and_(Document.id == str(doc_uuid), Document.tenant_id == tenant_id)
    )
    res = await db.execute(stmt)
    doc = res.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found or access denied")

    # Delete file on disk (ignore if already gone)
    file_path = Path("static") / "uploads" / doc.filename
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception:
        # Don't block DB delete if FS delete fails
        pass

    # Delete DB row
    await db.delete(doc)
    await db.commit()

    # Redirect back to list
    return RedirectResponse(
        url=str(request.url_for("view_documents")) + "?success=Document%20deleted",
        status_code=303,
    )