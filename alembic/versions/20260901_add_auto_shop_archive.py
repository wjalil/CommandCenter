"""auto_shop_archive

Revision ID: 20260901_auto_shop_archive
Revises: 20260827_cacfp_eligible
Create Date: 2026-09-01

Adds archived / archived_at columns to repair_orders so completed jobs can
leave the active board and land in an Archive view.
Idempotent — safe to run even if partially applied.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260901_auto_shop_archive"
down_revision: Union[str, None] = "20260827_cacfp_eligible"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return inspect(op.get_bind())


def _col_exists(table: str, column: str) -> bool:
    if not _inspector().has_table(table):
        return False
    return any(c["name"] == column for c in _inspector().get_columns(table))


def _index_exists(table: str, index_name: str) -> bool:
    if not _inspector().has_table(table):
        return False
    return any(i["name"] == index_name for i in _inspector().get_indexes(table))


def upgrade() -> None:
    if not _col_exists("repair_orders", "archived"):
        op.add_column(
            "repair_orders",
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not _col_exists("repair_orders", "archived_at"):
        op.add_column("repair_orders", sa.Column("archived_at", sa.DateTime(), nullable=True))

    if not _index_exists("repair_orders", "idx_repair_orders_archived"):
        op.create_index("idx_repair_orders_archived", "repair_orders", ["tenant_id", "archived"])


def downgrade() -> None:
    if _index_exists("repair_orders", "idx_repair_orders_archived"):
        op.drop_index("idx_repair_orders_archived", table_name="repair_orders")
    if _col_exists("repair_orders", "archived_at"):
        op.drop_column("repair_orders", "archived_at")
    if _col_exists("repair_orders", "archived"):
        op.drop_column("repair_orders", "archived")
