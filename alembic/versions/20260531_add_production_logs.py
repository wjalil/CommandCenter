"""add catering production daily logs

Revision ID: 20260531_production_logs
Revises: 20260531_am_pm_snack
Create Date: 2026-05-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260531_production_logs'
down_revision: Union[str, Sequence[str], None] = '20260531_am_pm_snack'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        'catering_production_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('service_date', sa.Date(), nullable=False),
        sa.Column('program_id', sa.String(), sa.ForeignKey('catering_programs.id', ondelete='CASCADE'), nullable=True),
        sa.Column('check_type', sa.String(), nullable=False),
        sa.Column('reference_key', sa.String(), nullable=True),
        sa.Column('checked_by_user_id', sa.String(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('checked_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_production_logs_date', 'catering_production_logs', ['tenant_id', 'service_date'])
    op.create_index('idx_production_logs_program', 'catering_production_logs', ['program_id'])


def downgrade():
    op.drop_index('idx_production_logs_program', table_name='catering_production_logs')
    op.drop_index('idx_production_logs_date', table_name='catering_production_logs')
    op.drop_table('catering_production_logs')
