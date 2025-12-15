"""add menu catergories

Revision ID: 1a723daceeeb
Revises: eec5f504557c
Create Date: 2025-12-14 15:56:17.202038

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a723daceeeb'
down_revision: Union[str, Sequence[str], None] = 'eec5f504557c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 1) Create menu_categories table
    op.create_table(
        "menu_categories",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("menu_id", sa.String(), sa.ForeignKey("menus.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )

    # Helpful indexes
    op.create_index("ix_menu_categories_tenant_id", "menu_categories", ["tenant_id"])
    op.create_index("ix_menu_categories_menu_id", "menu_categories", ["menu_id"])
    op.create_index(
        "ux_menu_categories_menu_id_name",
        "menu_categories",
        ["menu_id", "name"],
        unique=True,
    )

    # 2) Add category_id column to menu_items (nullable for back-compat)
    op.add_column("menu_items", sa.Column("category_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_menu_items_category_id",
        "menu_items",
        "menu_categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_menu_items_category_id", "menu_items", ["category_id"])


def downgrade():
    op.drop_index("ix_menu_items_category_id", table_name="menu_items")
    op.drop_constraint("fk_menu_items_category_id", "menu_items", type_="foreignkey")
    op.drop_column("menu_items", "category_id")

    op.drop_index("ux_menu_categories_menu_id_name", table_name="menu_categories")
    op.drop_index("ix_menu_categories_menu_id", table_name="menu_categories")
    op.drop_index("ix_menu_categories_tenant_id", table_name="menu_categories")
    op.drop_table("menu_categories")