from fastapi import APIRouter, Request, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.db import get_db
from app.models.document import Document
import uuid
import os
import shutil
from app.core.constants import UPLOAD_PATHS

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
    stmt = select(Document)
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
    # Generate safe filename
    original_filename = file.filename
    extension = os.path.splitext(original_filename)[1]
    new_filename = f"{uuid.uuid4()}{extension}"
    file_path = os.path.join(UPLOAD_DIR, new_filename)

    # Save file to disk
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Store metadata in database
    doc = Document(
        title=title,
        filename=new_filename,
        original_filename=original_filename,
        tags=tags
    )
    db.add(doc)
    await db.commit()

    return RedirectResponse(
        url=str(request.url_for("view_documents")) + "?success=Upload%20successful",
        status_code=303
    )


@router.get("/worker/documents")
async def worker_documents_view(
    request: Request,
    search: str = "",
    db: AsyncSession = Depends(get_db)
):
    if search:
        result = await db.execute(
            Document.__table__.select().where(Document.title.ilike(f"%{search}%"))
        )
    else:
        result = await db.execute(Document.__table__.select())

    documents = result.fetchall()

    return templates.TemplateResponse("worker_documents.html", {
        "request": request,
        "documents": documents,
        "search_query": search,
    })



@router.post("/admin/documents/delete/{doc_id}")
async def delete_document(doc_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalars().first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove file from disk
    file_path = os.path.join("static", "uploads", doc.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    # Delete from DB
    await db.delete(doc)
    await db.commit()

    return RedirectResponse(
        url=str(request.url_for("view_documents")) + "?success=Document%20deleted",
        status_code=303
    )