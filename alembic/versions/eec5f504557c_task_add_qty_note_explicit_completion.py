"""task: add qty, note, explicit completion

Revision ID: eec5f504557c
Revises: 20251022_fix_cbid_type
Create Date: 2025-10-22 21:44:52.281211

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eec5f504557c'
down_revision: Union[str, Sequence[str], None] = '20251022_fix_cbid_type'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column("daily_tasks", sa.Column("target_qty", sa.Integer(), nullable=True))
    op.add_column("daily_tasks", sa.Column("progress_qty", sa.Integer(), nullable=True))
    op.add_column("daily_tasks", sa.Column("progress_note", sa.Text(), nullable=True))

    # Constraints
    op.create_check_constraint(
        "ck_daily_tasks_target_qty_nonneg",
        "daily_tasks",
        "target_qty IS NULL OR target_qty >= 0"
    )
    op.create_check_constraint(
        "ck_daily_tasks_progress_qty_nonneg",
        "daily_tasks",
        "progress_qty IS NULL OR progress_qty >= 0"
    )
    op.create_check_constraint(
        "ck_daily_tasks_progress_le_target",
        "daily_tasks",
        "(target_qty IS NULL) OR (progress_qty IS NULL) OR (progress_qty <= target_qty)"
    )

    # Helpful composite index
    op.create_index(
        "ix_daily_tasks_tenant_date_completed",
        "daily_tasks",
        ["tenant_id", "task_date", "is_completed"]
    )

def downgrade():
    op.drop_index("ix_daily_tasks_tenant_date_completed", table_name="daily_tasks")
    for name in (
        "ck_daily_tasks_progress_le_target",
        "ck_daily_tasks_progress_qty_nonneg",
        "ck_daily_tasks_target_qty_nonneg",
    ):
        op.drop_constraint(name, "daily_tasks", type_="check")

    op.drop_column("daily_tasks", "progress_note")
    op.drop_column("daily_tasks", "progress_qty")
    op.drop_column("daily_tasks", "target_qty")