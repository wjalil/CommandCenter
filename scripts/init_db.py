# scripts/init_db.py
import asyncio
from app.db import engine
# This line will now import all models and make them visible to Base
from app.models.base import Base  # Triggers model discovery via __init__.py
# ⬇️ Force import of all models here
from app.models import task, shift, user, document  # 👈 this line ensures Document gets registered


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ All missing tables created.")

if __name__ == "__main__":
    asyncio.run(create_tables())
