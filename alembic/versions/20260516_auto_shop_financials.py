"""auto_shop_financials

Revision ID: 20260516_auto_shop_financials
Revises: 20260516_remap_statuses
Create Date: 2026-05-16

Adds financial columns to repair_orders and creates repair_order_payments table.
All operations are idempotent — safe to run even if partially applied.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260516_auto_shop_financials"
down_revision: Union[str, None] = "20260516_remap_statuses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return _inspector().has_table(name)


def _col_exists(table: str, column: str) -> bool:
    if not _table_exists(table):
        return False
    return any(c["name"] == column for c in _inspector().get_columns(table))


def _index_exists(table: str, index_name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(i["name"] == index_name for i in _inspector().get_indexes(table))


def upgrade() -> None:
    # ── financial columns on repair_orders ────────────────────────────────────
    new_cols = [
        ("payment_type",   sa.String()),
        ("claim_number",   sa.String()),
        ("deductible",     sa.Numeric(10, 2)),
        ("total_estimate", sa.Numeric(10, 2)),
        ("supplement_1",   sa.Numeric(10, 2)),
        ("supplement_2",   sa.Numeric(10, 2)),
        ("supplement_3",   sa.Numeric(10, 2)),
        ("supplement_4",   sa.Numeric(10, 2)),
    ]
    for col_name, col_type in new_cols:
        if not _col_exists("repair_orders", col_name):
            op.add_column("repair_orders", sa.Column(col_name, col_type, nullable=True))

    # ── repair_order_payments table ───────────────────────────────────────────
    if not _table_exists("repair_order_payments"):
        op.create_table(
            "repair_order_payments",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "repair_order_id",
                sa.String(),
                sa.ForeignKey("repair_orders.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("payment_method", sa.String(), nullable=False),
            sa.Column("amount", sa.Numeric(10, 2), nullable=False),
            sa.Column(
                "date_received",
                sa.Date(),
                nullable=False,
                server_default=sa.func.current_date(),
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )

    if not _index_exists("repair_order_payments", "idx_payments_order"):
        op.create_index("idx_payments_order", "repair_order_payments", ["repair_order_id"])

    if not _index_exists("repair_order_payments", "idx_payments_tenant"):
        op.create_index("idx_payments_tenant", "repair_order_payments", ["tenant_id"])


def downgrade() -> None:
    if _table_exists("repair_order_payments"):
        op.drop_table("repair_order_payments")
    # Columns added to repair_orders are left in place on downgrade
    # to avoid accidental data loss
