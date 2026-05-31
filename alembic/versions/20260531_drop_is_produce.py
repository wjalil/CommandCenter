"""Drop is_produce from food_components (replaced by component type filter)

Revision ID: 20260531_drop_is_produce
Revises: 20260531_is_produce
Create Date: 2026-05-31
"""
from typing import Union, Sequence
from alembic import op
import sqlalchemy as sa

revision: str = '20260531_drop_is_produce'
down_revision: Union[str, Sequence[str], None] = '20260531_is_produce'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('food_components', 'is_produce')


def downgrade() -> None:
    op.add_column(
        'food_components',
        sa.Column('is_produce', sa.Boolean(), nullable=False, server_default='false')
    )
