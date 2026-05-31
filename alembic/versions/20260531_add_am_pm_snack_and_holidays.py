"""add AM/PM snack meal types and holiday invoice skipping

Revision ID: 20260531_am_pm_snack
Revises: 20260517_add_tracking_token
Create Date: 2026-05-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260531_am_pm_snack'
down_revision: Union[str, Sequence[str], None] = '20260517_add_tracking_token'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Add AM Snack and PM Snack columns to catering_menu_days
    op.add_column('catering_menu_days', sa.Column('am_snack_item_id', sa.String(), sa.ForeignKey('catering_meal_items.id'), nullable=True))
    op.add_column('catering_menu_days', sa.Column('am_snack_vegan_item_id', sa.String(), sa.ForeignKey('catering_meal_items.id'), nullable=True))
    op.add_column('catering_menu_days', sa.Column('pm_snack_item_id', sa.String(), sa.ForeignKey('catering_meal_items.id'), nullable=True))
    op.add_column('catering_menu_days', sa.Column('pm_snack_vegan_item_id', sa.String(), sa.ForeignKey('catering_meal_items.id'), nullable=True))

    # Add AM Snack and PM Snack count columns to catering_invoices
    op.add_column('catering_invoices', sa.Column('am_snack_count', sa.Integer(), nullable=True))
    op.add_column('catering_invoices', sa.Column('am_snack_vegan_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('catering_invoices', sa.Column('pm_snack_count', sa.Integer(), nullable=True))
    op.add_column('catering_invoices', sa.Column('pm_snack_vegan_count', sa.Integer(), nullable=False, server_default='0'))

    # Add AM Snack and PM Snack count columns to catering_programs
    op.add_column('catering_programs', sa.Column('am_snack_count', sa.Integer(), nullable=True))
    op.add_column('catering_programs', sa.Column('pm_snack_count', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('catering_programs', 'pm_snack_count')
    op.drop_column('catering_programs', 'am_snack_count')

    op.drop_column('catering_invoices', 'pm_snack_vegan_count')
    op.drop_column('catering_invoices', 'pm_snack_count')
    op.drop_column('catering_invoices', 'am_snack_vegan_count')
    op.drop_column('catering_invoices', 'am_snack_count')

    op.drop_column('catering_menu_days', 'pm_snack_vegan_item_id')
    op.drop_column('catering_menu_days', 'pm_snack_item_id')
    op.drop_column('catering_menu_days', 'am_snack_vegan_item_id')
    op.drop_column('catering_menu_days', 'am_snack_item_id')
