"""add catering_daily_counts table for same-day headcount overrides

Lets kitchen staff edit a program's meal-slot headcount for a single service date
on the Production Sheet (e.g. "22 kids today, not the usual 25"), without touching
the program's standing count. Empty by default — only holds exceptions. Both the
kitchen-prep aggregation and invoice generation fall back to the program's standing
count (program.<slot>_count) whenever no row exists here.

Revision ID: 20260921_daily_counts
Revises: 20260913b_manifest_routes
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260921_daily_counts'
down_revision: Union[str, Sequence[str], None] = '20260913b_manifest_routes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The app's startup create_all() may already have created this table (and its
    # indexes) before this migration ran — only create what's missing.
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('catering_daily_counts'):
        existing = {ix['name'] for ix in inspector.get_indexes('catering_daily_counts')}
        if 'idx_daily_counts_program_date' not in existing:
            op.create_index('idx_daily_counts_program_date', 'catering_daily_counts', ['program_id', 'service_date'])
        if 'idx_daily_counts_tenant_date' not in existing:
            op.create_index('idx_daily_counts_tenant_date', 'catering_daily_counts', ['tenant_id', 'service_date'])
        return

    op.create_table(
        'catering_daily_counts',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('program_id', sa.String(), sa.ForeignKey('catering_programs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('service_date', sa.Date(), nullable=False),
        sa.Column('meal_slot', sa.String(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('vegan_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_by_user_id', sa.String(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('program_id', 'service_date', 'meal_slot', name='uq_daily_count_program_date_slot'),
    )
    op.create_index('idx_daily_counts_program_date', 'catering_daily_counts', ['program_id', 'service_date'])
    op.create_index('idx_daily_counts_tenant_date', 'catering_daily_counts', ['tenant_id', 'service_date'])


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS catering_daily_counts CASCADE")
