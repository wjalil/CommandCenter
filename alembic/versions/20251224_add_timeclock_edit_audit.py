"""add timeclock edit audit fields

Revision ID: 20251224_timeclock
Revises: d34f91888ad6
Create Date: 2025-12-24 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20251224_timeclock'
down_revision: Union[str, Sequence[str], None] = 'd34f91888ad6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add audit fields for timeclock edits and manual entries"""
    # Add columns as nullable (safe for existing data)
    op.add_column("time_entries", sa.Column("created_by_id", sa.String(), nullable=True))
    op.add_column("time_entries", sa.Column("edited_by_id", sa.String(), nullable=True))
    op.add_column("time_entries", sa.Column("edited_at", sa.DateTime(), nullable=True))
    op.add_column("time_entries", sa.Column("is_manual", sa.Boolean(), nullable=True))
    op.add_column("time_entries", sa.Column("edit_reason", sa.String(), nullable=True))

    # Set default for is_manual on existing rows (they're all clock-ins)
    op.execute("UPDATE time_entries SET is_manual = false WHERE is_manual IS NULL")

    # Alter is_manual to NOT NULL with default
    op.alter_column("time_entries", "is_manual", nullable=False, server_default=sa.text("false"))

    # Add foreign key constraints
    op.create_foreign_key(
        "fk_time_entries_created_by_id", "time_entries", "users",
        ["created_by_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_time_entries_edited_by_id", "time_entries", "users",
        ["edited_by_id"], ["id"], ondelete="SET NULL"
    )

    # Add index for edited entries (for quick filtering)
    op.create_index("ix_time_entries_edited", "time_entries", ["edited_at"])


def downgrade() -> None:
    """Remove audit fields"""
    op.drop_index("ix_time_entries_edited", table_name="time_entries")
    op.drop_constraint("fk_time_entries_edited_by_id", "time_entries", type_="foreignkey")
    op.drop_constraint("fk_time_entries_created_by_id", "time_entries", type_="foreignkey")
    op.drop_column("time_entries", "edit_reason")
    op.drop_column("time_entries", "is_manual")
    op.drop_column("time_entries", "edited_at")
    op.drop_column("time_entries", "edited_by_id")
    op.drop_column("time_entries", "created_by_id")
