"""add route_code, meal_service_style, special_instructions to catering programs

Revision ID: 20260912_route_style_instr
Revises: 20260901_auto_shop_archive
Create Date: 2026-09-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260912_route_style_instr'
down_revision: Union[str, Sequence[str], None] = '20260901_auto_shop_archive'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Additive only — new nullable columns on catering_programs."""
    op.add_column('catering_programs', sa.Column('route_code', sa.String(), nullable=True))
    op.add_column('catering_programs', sa.Column('meal_service_style', sa.String(), nullable=True))
    op.add_column('catering_programs', sa.Column('special_instructions', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('catering_programs', 'special_instructions')
    op.drop_column('catering_programs', 'meal_service_style')
    op.drop_column('catering_programs', 'route_code')
