"""add_tracking_token_to_repair_orders

Revision ID: 20260517_add_tracking_token
Revises: 20260516_auto_shop_financials
Create Date: 2026-05-17

Adds tracking_token column to repair_orders so customers can view
their repair status via a public URL without logging in.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260517_add_tracking_token"
down_revision: Union[str, None] = "20260516_auto_shop_financials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(table: str, column: str) -> bool:
    insp = inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _col_exists("repair_orders", "tracking_token"):
        op.add_column(
            "repair_orders",
            sa.Column("tracking_token", sa.String(), nullable=True, unique=True),
        )


def downgrade() -> None:
    # Leave column in place on downgrade to avoid accidental data loss
    pass
