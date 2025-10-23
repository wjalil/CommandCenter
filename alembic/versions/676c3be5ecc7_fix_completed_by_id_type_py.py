"""fix_completed_by_id_type.py

Revision ID: 676c3be5ecc7
Revises: 20251022_create_daily_tasks
Create Date: 2025-10-22 17:39:12.527488

"""
# alembic/versions/20251022_fix_completed_by_id_type.py
from alembic import op
import sqlalchemy as sa

revision = "20251022_fix_cbid_type"
down_revision = "20251022_create_daily_tasks"  # or your actual previous revision id
branch_labels = None
depends_on = None

def upgrade():
    # 1) Drop existing FK (name is usually this; adjust if yours differs)
    op.drop_constraint("daily_tasks_completed_by_id_fkey", "daily_tasks", type_="foreignkey")

    # 2) Alter column type from integer -> text/varchar
    op.alter_column(
        "daily_tasks",
        "completed_by_id",
        existing_type=sa.Integer(),
        type_=sa.String(),
        postgresql_using="completed_by_id::text",
        existing_nullable=True,
    )

    # 3) Recreate FK to users.id with SET NULL
    op.create_foreign_key(
        "fk_daily_tasks_completed_by_user",
        "daily_tasks",
        "users",
        ["completed_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

def downgrade():
    op.drop_constraint("fk_daily_tasks_completed_by_user", "daily_tasks", type_="foreignkey")
    op.alter_column(
        "daily_tasks",
        "completed_by_id",
        existing_type=sa.String(),
        type_=sa.Integer(),
        postgresql_using="NULLIF(completed_by_id, '')::integer",
        existing_nullable=True,
    )
    op.create_foreign_key(
        "daily_tasks_completed_by_id_fkey",
        "daily_tasks",
        "users",
        ["completed_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
