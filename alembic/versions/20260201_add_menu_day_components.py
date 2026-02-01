"""add_menu_day_components

Revision ID: 20260201_menu_day_components
Revises: a1b2c3d4e5f6
Create Date: 2026-02-01

Adds menu_day_components table for component-first menu building.
This allows direct assignment of FoodComponents to MenuDays without
needing to pre-create MealItem combinations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260201_menu_day_components'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Create menu_day_components table
    op.create_table(
        'menu_day_components',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('menu_day_id', sa.String(), sa.ForeignKey('catering_menu_days.id', ondelete='CASCADE'), nullable=False),
        sa.Column('component_id', sa.Integer(), sa.ForeignKey('food_components.id'), nullable=False),
        sa.Column('meal_slot', sa.String(), nullable=False),  # breakfast, lunch, snack
        sa.Column('is_vegan', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('quantity', sa.Numeric(5, 2), nullable=True),  # Optional portion override
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # Add unique constraint to prevent duplicate component assignments
    op.create_unique_constraint(
        'uq_menu_day_component',
        'menu_day_components',
        ['menu_day_id', 'component_id', 'meal_slot', 'is_vegan']
    )

    # Add indexes for efficient querying
    op.create_index('idx_menu_day_components_day', 'menu_day_components', ['menu_day_id'])
    op.create_index('idx_menu_day_components_slot', 'menu_day_components', ['menu_day_id', 'meal_slot'])


def downgrade():
    op.drop_index('idx_menu_day_components_slot', table_name='menu_day_components')
    op.drop_index('idx_menu_day_components_day', table_name='menu_day_components')
    op.drop_constraint('uq_menu_day_component', 'menu_day_components', type_='unique')
    op.drop_table('menu_day_components')
