"""Add sort_order to menu_day_components

Revision ID: 20260201_component_sort
Revises: 20260201_menu_day_components
Create Date: 2026-02-01 12:00:00.000000

This migration ONLY adds a sort_order column to menu_day_components.
No other tables are affected.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260201_component_sort'
down_revision = '20260201_menu_day_components'
branch_labels = None
depends_on = None


def upgrade():
    # ONLY add sort_order column to menu_day_components - no other changes
    op.add_column('menu_day_components', sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    # ONLY remove the sort_order column - no other changes
    op.drop_column('menu_day_components', 'sort_order')
