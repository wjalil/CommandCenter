"""add driver manifest tables + breakfast/lunch pack notes on catering programs

Revision ID: 20260913_daily_manifest
Revises: 20260912_route_style_instr
Create Date: 2026-09-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260913_daily_manifest'
down_revision: Union[str, Sequence[str], None] = '20260912_route_style_instr'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Additive only — new nullable columns + two new tables."""
    op.add_column('catering_programs', sa.Column('breakfast_pack_note', sa.String(), nullable=True))
    op.add_column('catering_programs', sa.Column('lunch_pack_note', sa.String(), nullable=True))

    op.create_table(
        'catering_daily_manifests',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('program_id', sa.String(), sa.ForeignKey('catering_programs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('service_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='draft'),
        sa.Column('special_instructions', sa.Text(), nullable=True),
        sa.Column('released_at', sa.DateTime(), nullable=True),
        sa.Column('released_by_user_id', sa.String(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('tenant_id', 'program_id', 'service_date', name='uq_daily_manifest_program_date'),
    )
    op.create_index('idx_daily_manifests_date', 'catering_daily_manifests', ['tenant_id', 'service_date'])
    op.create_index('idx_daily_manifests_program', 'catering_daily_manifests', ['program_id'])

    op.create_table(
        'catering_daily_manifest_items',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('manifest_id', sa.String(), sa.ForeignKey('catering_daily_manifests.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('driver_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('driver_confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('driver_confirmed_by_user_id', sa.String(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('idx_daily_manifest_items_manifest', 'catering_daily_manifest_items', ['manifest_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_daily_manifest_items_manifest', table_name='catering_daily_manifest_items')
    op.drop_table('catering_daily_manifest_items')

    op.drop_index('idx_daily_manifests_program', table_name='catering_daily_manifests')
    op.drop_index('idx_daily_manifests_date', table_name='catering_daily_manifests')
    op.drop_table('catering_daily_manifests')

    op.drop_column('catering_programs', 'lunch_pack_note')
    op.drop_column('catering_programs', 'breakfast_pack_note')
