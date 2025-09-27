# alembic/env.py
from __future__ import annotations
import os
from logging.config import fileConfig

from alembic import context

# --- Load env like your app does
from dotenv import load_dotenv
# Prefer .env.production if present, else default .env
if os.path.exists(".env.production"):
    load_dotenv(".env.production")
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set for Alembic")

# --- Your models' metadata
from app.models.base import Base  # same Base you use in app
import app.models  # IMPORTANT: import to register all model classes

target_metadata = Base.metadata

# --- Optional: enable type comparison (so autogenerate picks up type changes)
COMPARE_TYPE = True

# --- Logging
config = context.config
fileConfig(config.config_file_name) if config.config_file_name else None

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=COMPARE_TYPE,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=COMPARE_TYPE,
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode' using your ASYNC URL."""
    # Alembic will open a sync context; we adapt via run_sync
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)

    async def _run():
        async with engine.connect() as conn:
            await conn.run_sync(do_run_migrations)
        await engine.dispose()

    import asyncio
    asyncio.run(_run())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
