"""restructure driver manifest to route-level (Route -> Stop -> Item)

The manifest previously lived one-per-program. It now lives one-per-top-level-route
(e.g. "R1"), with a new "stops" table holding each program's items and per-stop
special instructions under that route. This DROPS the two manifest tables created
in 20260913_daily_manifest and recreates them in the new shape — any manifest/item
test data entered against the old schema is lost. breakfast_pack_note/lunch_pack_note
on catering_programs are untouched.

Revision ID: 20260913b_manifest_routes
Revises: 20260913_daily_manifest
Create Date: 2026-09-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260913b_manifest_routes'
down_revision: Union[str, Sequence[str], None] = '20260913_daily_manifest'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Drops and recreates the manifest tables in the new route/stop/item shape.

    Uses IF EXISTS ... CASCADE (rather than alembic's plain drop_table/drop_index) so this
    is safe to re-run even if an earlier attempt got partway through — e.g. created the new
    catering_daily_manifest_stops table — without alembic recording the revision as applied.
    CASCADE also means we don't need to drop indexes/constraints separately; dropping the
    table takes them with it.
    """
    op.execute("DROP TABLE IF EXISTS catering_daily_manifest_items CASCADE")
    op.execute("DROP TABLE IF EXISTS catering_daily_manifest_stops CASCADE")
    op.execute("DROP TABLE IF EXISTS catering_daily_manifests CASCADE")

    op.create_table(
        'catering_daily_manifests',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('route_code', sa.String(), nullable=False),
        sa.Column('service_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='draft'),
        sa.Column('released_at', sa.DateTime(), nullable=True),
        sa.Column('released_by_user_id', sa.String(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('tenant_id', 'route_code', 'service_date', name='uq_daily_manifest_route_date'),
    )
    op.create_index('idx_daily_manifests_date', 'catering_daily_manifests', ['tenant_id', 'service_date'])

    op.create_table(
        'catering_daily_manifest_stops',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('manifest_id', sa.String(), sa.ForeignKey('catering_daily_manifests.id', ondelete='CASCADE'), nullable=False),
        sa.Column('program_id', sa.String(), sa.ForeignKey('catering_programs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('special_instructions', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('manifest_id', 'program_id', name='uq_daily_manifest_stop_program'),
    )
    op.create_index('idx_daily_manifest_stops_manifest', 'catering_daily_manifest_stops', ['manifest_id'])
    op.create_index('idx_daily_manifest_stops_program', 'catering_daily_manifest_stops', ['program_id'])

    op.create_table(
        'catering_daily_manifest_items',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('stop_id', sa.String(), sa.ForeignKey('catering_daily_manifest_stops.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('driver_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('driver_confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('driver_confirmed_by_user_id', sa.String(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('idx_daily_manifest_items_stop', 'catering_daily_manifest_items', ['stop_id'])


def downgrade() -> None:
    """Downgrade schema. Drops the route/stop/item tables and recreates the old program-level shape (empty)."""
    op.execute("DROP TABLE IF EXISTS catering_daily_manifest_items CASCADE")
    op.execute("DROP TABLE IF EXISTS catering_daily_manifest_stops CASCADE")
    op.execute("DROP TABLE IF EXISTS catering_daily_manifests CASCADE")

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
