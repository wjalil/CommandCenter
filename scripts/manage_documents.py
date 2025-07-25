# scripts/manage_documents.py
import asyncio
from app.db import async_session
from app.models.document import Document

async def list_documents():
    async with async_session() as session:
        result = await session.execute(Document.__table__.select())
        docs = result.fetchall()
        if not docs:
            print("📂 No documents found.")
            return []

        print("\n📋 Documents:")
        for i, doc in enumerate(docs):
            print(f"{i+1}. {doc.title} | {doc.original_filename} | {doc.tags} | {doc.id}")
        return docs

async def delete_document_by_id(doc_id):
    async with async_session() as session:
        result = await session.execute(Document.__table__.delete().where(Document.id == doc_id))
        await session.commit()
        print(f"🗑️ Deleted document with ID: {doc_id}")

async def main():
    docs = await list_documents()
    if not docs:
        return

    choice = input("\nEnter the # of the document to delete (or 'q' to quit): ")
    if choice.lower() == 'q':
        print("👋 Exit without deletion.")
        return

    try:
        index = int(choice) - 1
        selected_doc = docs[index]
        confirm = input(f"⚠️ Confirm delete '{selected_doc.title}'? (y/n): ")
        if confirm.lower() == 'y':
            await delete_document_by_id(selected_doc.id)
        else:
            print("❌ Deletion canceled.")
    except (IndexError, ValueError):
        print("❗ Invalid selection.")

if __name__ == "__main__":
    asyncio.run(main())
