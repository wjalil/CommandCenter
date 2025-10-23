"""create daily_tasks table

Revision ID: aa8cb25bb772
Revises: 20251022_create_daily_tasks
Create Date: 2025-10-22 16:06:53.807424

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision = "20251022_create_daily_tasks"
down_revision = "20251011_timeclock_v2"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "daily_tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),

        sa.Column("title", sa.String(), nullable=False),
        sa.Column("details", sa.String(), nullable=True),

        sa.Column("task_date", sa.Date(), nullable=True),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=True),
        sa.Column("shift_label", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),

        sa.Column("is_completed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        # after
        sa.Column("completed_by_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),

        # Use UTC now() server defaults so writes from any app node are consistent
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=False),

        sa.Column("order_index", sa.SmallInteger(), server_default="0", nullable=False),
    )

    # Helpful indexes for your common filters
    op.create_index("ix_daily_tasks_tenant_date", "daily_tasks", ["tenant_id", "task_date"])
    op.create_index("ix_daily_tasks_tenant_dow", "daily_tasks", ["tenant_id", "day_of_week"])
    op.create_index("ix_daily_tasks_tenant_role", "daily_tasks", ["tenant_id", "role"])
    op.create_index("ix_daily_tasks_tenant_shift", "daily_tasks", ["tenant_id", "shift_label"])

    # Optional: keep day_of_week in 1..7
    op.create_check_constraint(
        "ck_daily_tasks_day_of_week_range",
        "daily_tasks",
        "day_of_week IS NULL OR (day_of_week BETWEEN 1 AND 7)"
    )

def downgrade():
    op.drop_constraint("ck_daily_tasks_day_of_week_range", "daily_tasks", type_="check")
    op.drop_index("ix_daily_tasks_tenant_shift", table_name="daily_tasks")
    op.drop_index("ix_daily_tasks_tenant_role", table_name="daily_tasks")
    op.drop_index("ix_daily_tasks_tenant_dow", table_name="daily_tasks")
    op.drop_index("ix_daily_tasks_tenant_date", table_name="daily_tasks")
    op.drop_table("daily_tasks")
