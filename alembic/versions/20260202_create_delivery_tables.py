"""create_delivery_tables

Revision ID: 20260202_delivery
Revises: 20260201_component_sort
Create Date: 2026-02-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '20260202_delivery'
down_revision: Union[str, Sequence[str], None] = '20260201_component_sort'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name):
    """Check if a table exists in the database"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def index_exists(table_name, index_name):
    """Check if an index exists on a table"""
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = inspector.get_indexes(table_name)
    return any(idx['name'] == index_name for idx in indexes)


def upgrade():
    # 1. Delivery Stops (reusable locations)
    if not table_exists('delivery_stops'):
        op.create_table(
            'delivery_stops',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('address', sa.String(), nullable=True),
            sa.Column('contact_name', sa.String(), nullable=True),
            sa.Column('contact_phone', sa.String(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        )

    if table_exists('delivery_stops'):
        if not index_exists('delivery_stops', 'idx_delivery_stops_tenant'):
            op.create_index('idx_delivery_stops_tenant', 'delivery_stops', ['tenant_id'])
        if not index_exists('delivery_stops', 'idx_delivery_stops_active'):
            op.create_index('idx_delivery_stops_active', 'delivery_stops', ['tenant_id', 'is_active'])

    # 2. Delivery Routes (daily routes)
    if not table_exists('delivery_routes'):
        op.create_table(
            'delivery_routes',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('assigned_driver_id', sa.String(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('status', sa.String(), nullable=False, server_default='draft'),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )

    if table_exists('delivery_routes'):
        if not index_exists('delivery_routes', 'idx_delivery_routes_tenant'):
            op.create_index('idx_delivery_routes_tenant', 'delivery_routes', ['tenant_id'])
        if not index_exists('delivery_routes', 'idx_delivery_routes_date'):
            op.create_index('idx_delivery_routes_date', 'delivery_routes', ['tenant_id', 'date'])
        if not index_exists('delivery_routes', 'idx_delivery_routes_driver'):
            op.create_index('idx_delivery_routes_driver', 'delivery_routes', ['assigned_driver_id'])

    # 3. Delivery Route Stops (junction table with tracking)
    if not table_exists('delivery_route_stops'):
        op.create_table(
            'delivery_route_stops',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('route_id', sa.String(), sa.ForeignKey('delivery_routes.id', ondelete='CASCADE'), nullable=False),
            sa.Column('stop_id', sa.String(), sa.ForeignKey('delivery_stops.id', ondelete='CASCADE'), nullable=False),
            sa.Column('stop_order', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='pending'),
            sa.Column('arrival_time', sa.DateTime(), nullable=True),
            sa.Column('departure_time', sa.DateTime(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('photo_filename', sa.String(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
        )

    if table_exists('delivery_route_stops'):
        if not index_exists('delivery_route_stops', 'idx_route_stops_route'):
            op.create_index('idx_route_stops_route', 'delivery_route_stops', ['route_id'])
        if not index_exists('delivery_route_stops', 'idx_route_stops_stop'):
            op.create_index('idx_route_stops_stop', 'delivery_route_stops', ['stop_id'])


def downgrade():
    if table_exists('delivery_route_stops'):
        op.drop_table('delivery_route_stops')
    if table_exists('delivery_routes'):
        op.drop_table('delivery_routes')
    if table_exists('delivery_stops'):
        op.drop_table('delivery_stops')
