"""add_menu_type_to_monthly_menus

Revision ID: 20260222_menu_type
Revises: 20260202_delivery
Create Date: 2026-02-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260222_menu_type"
down_revision: Union[str, None] = "20260202_delivery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add menu_type column with default 'regular' for existing rows
    op.add_column(
        "catering_monthly_menus",
        sa.Column("menu_type", sa.String(), nullable=False, server_default="regular")
    )

    # Drop old unique constraint (program_id, month, year)
    op.drop_constraint("uq_monthly_menu", "catering_monthly_menus", type_="unique")

    # Create new unique constraint that includes menu_type
    op.create_unique_constraint(
        "uq_monthly_menu",
        "catering_monthly_menus",
        ["program_id", "month", "year", "menu_type"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_monthly_menu", "catering_monthly_menus", type_="unique")

    op.create_unique_constraint(
        "uq_monthly_menu",
        "catering_monthly_menus",
        ["program_id", "month", "year"]
    )

    op.drop_column("catering_monthly_menus", "menu_type")
