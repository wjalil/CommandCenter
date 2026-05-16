"""create_auto_shop_tables

Revision ID: 20260506_auto_shop
Revises: 20260222_menu_type
Create Date: 2026-05-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260506_auto_shop"
down_revision: Union[str, None] = "20260222_menu_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    # 1. repair_orders
    if not table_exists("repair_orders"):
        op.create_table(
            "repair_orders",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("ticket_number", sa.String(), nullable=False),
            sa.Column("vehicle_make", sa.String(), nullable=True),
            sa.Column("vehicle_model", sa.String(), nullable=True),
            sa.Column("vehicle_year", sa.String(), nullable=True),
            sa.Column("vehicle_color", sa.String(), nullable=True),
            sa.Column("vehicle_vin", sa.String(), nullable=True),
            sa.Column("vehicle_license_plate", sa.String(), nullable=True),
            sa.Column("vehicle_mileage", sa.Integer(), nullable=True),
            sa.Column("customer_name", sa.String(), nullable=False),
            sa.Column("customer_phone", sa.String(), nullable=True),
            sa.Column("customer_email", sa.String(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("internal_notes", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="intake"),
            sa.Column(
                "assigned_tech_id",
                sa.String(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column("intake_date", sa.Date(), nullable=False, server_default=sa.func.current_date()),
            sa.Column("estimated_completion", sa.Date(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id"),
                nullable=False,
            ),
        )

    if table_exists("repair_orders"):
        if not index_exists("repair_orders", "idx_repair_orders_tenant"):
            op.create_index("idx_repair_orders_tenant", "repair_orders", ["tenant_id"])
        if not index_exists("repair_orders", "idx_repair_orders_status"):
            op.create_index("idx_repair_orders_status", "repair_orders", ["tenant_id", "status"])
        if not index_exists("repair_orders", "idx_repair_orders_intake"):
            op.create_index("idx_repair_orders_intake", "repair_orders", ["tenant_id", "intake_date"])

    # 2. repair_order_photos
    if not table_exists("repair_order_photos"):
        op.create_table(
            "repair_order_photos",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "repair_order_id",
                sa.String(),
                sa.ForeignKey("repair_orders.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("original_filename", sa.String(), nullable=False),
            sa.Column("caption", sa.String(), nullable=True),
            sa.Column("category", sa.String(), nullable=True),
            sa.Column(
                "uploaded_by_id",
                sa.String(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column("uploaded_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id"),
                nullable=False,
            ),
        )

    if table_exists("repair_order_photos"):
        if not index_exists("repair_order_photos", "idx_repair_photos_order"):
            op.create_index("idx_repair_photos_order", "repair_order_photos", ["repair_order_id"])
        if not index_exists("repair_order_photos", "idx_repair_photos_tenant"):
            op.create_index("idx_repair_photos_tenant", "repair_order_photos", ["tenant_id"])

    # 3. repair_order_status_logs
    if not table_exists("repair_order_status_logs"):
        op.create_table(
            "repair_order_status_logs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "repair_order_id",
                sa.String(),
                sa.ForeignKey("repair_orders.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("old_status", sa.String(), nullable=True),
            sa.Column("new_status", sa.String(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "changed_by_id",
                sa.String(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column("changed_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("sms_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id"),
                nullable=False,
            ),
        )

    if table_exists("repair_order_status_logs"):
        if not index_exists("repair_order_status_logs", "idx_status_logs_order"):
            op.create_index("idx_status_logs_order", "repair_order_status_logs", ["repair_order_id"])
        if not index_exists("repair_order_status_logs", "idx_status_logs_tenant"):
            op.create_index("idx_status_logs_tenant", "repair_order_status_logs", ["tenant_id"])


def downgrade() -> None:
    if table_exists("repair_order_status_logs"):
        op.drop_table("repair_order_status_logs")
    if table_exists("repair_order_photos"):
        op.drop_table("repair_order_photos")
    if table_exists("repair_orders"):
        op.drop_table("repair_orders")
