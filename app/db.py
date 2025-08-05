from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from app.models.base import Base
import os

# Load environment
load_dotenv(dotenv_path=".env.production")  # Or just load default .env if running locally

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL is not set!")

# Create engine
engine = create_async_engine(DATABASE_URL, echo=True)

# Async session maker
async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Dependency
async def get_db():
    async with async_session() as session:
        yield session

async def create_db_and_tables():
    import app.models  # triggers __init__.py

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Reusable engine getter
def get_async_engine():
    return engine
