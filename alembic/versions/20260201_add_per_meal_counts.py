"""add_per_meal_counts

Add per-meal-type counts to programs and invoices for accurate
tracking when breakfast/lunch/snack have different headcounts.

Revision ID: a1b2c3d4e5f6
Revises: d34f91888ad6
Create Date: 2026-02-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '20251224_timeclock'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Add per-meal counts to catering_programs
    op.add_column('catering_programs', sa.Column('breakfast_count', sa.Integer(), nullable=True))
    op.add_column('catering_programs', sa.Column('breakfast_vegan_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('catering_programs', sa.Column('lunch_count', sa.Integer(), nullable=True))
    op.add_column('catering_programs', sa.Column('lunch_vegan_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('catering_programs', sa.Column('snack_count', sa.Integer(), nullable=True))

    # Add per-meal counts to catering_invoices
    op.add_column('catering_invoices', sa.Column('breakfast_count', sa.Integer(), nullable=True))
    op.add_column('catering_invoices', sa.Column('breakfast_vegan_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('catering_invoices', sa.Column('lunch_count', sa.Integer(), nullable=True))
    op.add_column('catering_invoices', sa.Column('lunch_vegan_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('catering_invoices', sa.Column('snack_count', sa.Integer(), nullable=True))
    op.add_column('catering_invoices', sa.Column('snack_vegan_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    # Remove from catering_invoices
    op.drop_column('catering_invoices', 'snack_vegan_count')
    op.drop_column('catering_invoices', 'snack_count')
    op.drop_column('catering_invoices', 'lunch_vegan_count')
    op.drop_column('catering_invoices', 'lunch_count')
    op.drop_column('catering_invoices', 'breakfast_vegan_count')
    op.drop_column('catering_invoices', 'breakfast_count')

    # Remove from catering_programs
    op.drop_column('catering_programs', 'snack_count')
    op.drop_column('catering_programs', 'lunch_vegan_count')
    op.drop_column('catering_programs', 'lunch_count')
    op.drop_column('catering_programs', 'breakfast_vegan_count')
    op.drop_column('catering_programs', 'breakfast_count')
