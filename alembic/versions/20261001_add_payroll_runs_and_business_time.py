"""Friday payroll: pay runs, pay stubs with worker sign-off, business timezone

- tenants.timezone / pay_week_end_weekday / payroll_start_date
- payroll_runs, pay_stubs (frozen per-worker receipt + acknowledgment)
- time_entries.pay_run_id, delivery_routes.pay_run_id (what paid it)

No existing data changes: timestamps were already stored as UTC; pay runs start
from the first time Friday Payroll is opened (payroll_start_date is set then).

Idempotent: app startup's create_all() may already have created the new tables.

Revision ID: 20261001_payroll
Revises: 20260930_subs_ddi
Create Date: 2026-10-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20261001_payroll'
down_revision: Union[str, Sequence[str], None] = '20260930_subs_ddi'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return _insp().has_table(name)


def _has_column(table, column):
    return any(c["name"] == column for c in _insp().get_columns(table))


def _has_index(table, index):
    return any(i["name"] == index for i in _insp().get_indexes(table))


def _add_column(table, column):
    if not _has_column(table, column.name):
        op.add_column(table, column)


def _create_index(name, table, columns, unique=False):
    if not _has_index(table, name):
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    _add_column('tenants', sa.Column('timezone', sa.String(), nullable=True))
    _add_column('tenants', sa.Column('pay_week_end_weekday', sa.Integer(), nullable=True))
    _add_column('tenants', sa.Column('payroll_start_date', sa.Date(), nullable=True))

    if not _has_table('payroll_runs'):
        op.create_table(
            'payroll_runs',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
            sa.Column('period_start', sa.Date(), nullable=False),
            sa.Column('period_end', sa.Date(), nullable=False),
            sa.Column('paid_at', sa.DateTime(), nullable=False),
            sa.Column('paid_by_id', sa.String(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('payment_method', sa.String(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('worker_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('total_minutes', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('total_hourly', sa.Numeric(10, 2), nullable=False, server_default='0'),
            sa.Column('total_route_pay', sa.Numeric(10, 2), nullable=False, server_default='0'),
            sa.Column('total_gross', sa.Numeric(10, 2), nullable=False, server_default='0'),
        )
    _create_index('idx_payroll_runs_tenant_period', 'payroll_runs', ['tenant_id', 'period_end'])

    if not _has_table('pay_stubs'):
        op.create_table(
            'pay_stubs',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
            sa.Column('pay_run_id', sa.String(), sa.ForeignKey('payroll_runs.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.String(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('worker_name', sa.String(), nullable=True),
            sa.Column('period_start', sa.Date(), nullable=False),
            sa.Column('period_end', sa.Date(), nullable=False),
            sa.Column('minutes', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('hourly_gross', sa.Numeric(10, 2), nullable=False, server_default='0'),
            sa.Column('route_pay', sa.Numeric(10, 2), nullable=False, server_default='0'),
            sa.Column('total_gross', sa.Numeric(10, 2), nullable=False, server_default='0'),
            sa.Column('lines_json', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='issued'),
            sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
            sa.Column('signature_name', sa.String(), nullable=True),
            sa.Column('ack_ip', sa.String(), nullable=True),
            sa.Column('ack_user_agent', sa.String(), nullable=True),
            sa.Column('dispute_note', sa.Text(), nullable=True),
            sa.Column('disputed_at', sa.DateTime(), nullable=True),
            sa.Column('resolved_at', sa.DateTime(), nullable=True),
            sa.Column('resolution_note', sa.Text(), nullable=True),
            sa.UniqueConstraint('pay_run_id', 'user_id', name='uq_pay_stub_run_user'),
        )
    _create_index('idx_pay_stubs_user', 'pay_stubs', ['tenant_id', 'user_id'])

    _add_column('time_entries', sa.Column(
        'pay_run_id', sa.String(), sa.ForeignKey('payroll_runs.id', ondelete='SET NULL'), nullable=True))
    _create_index('ix_time_entries_pay_run_id', 'time_entries', ['pay_run_id'])
    _add_column('delivery_routes', sa.Column(
        'pay_run_id', sa.String(), sa.ForeignKey('payroll_runs.id', ondelete='SET NULL'), nullable=True))
    _create_index('ix_delivery_routes_pay_run_id', 'delivery_routes', ['pay_run_id'])


def downgrade() -> None:
    for table in ('delivery_routes', 'time_entries'):
        if _has_index(table, f'ix_{table}_pay_run_id'):
            op.drop_index(f'ix_{table}_pay_run_id', table_name=table)
        if _has_column(table, 'pay_run_id'):
            op.drop_column(table, 'pay_run_id')
    if _has_table('pay_stubs'):
        op.drop_table('pay_stubs')
    if _has_table('payroll_runs'):
        op.drop_table('payroll_runs')
    for col in ('payroll_start_date', 'pay_week_end_weekday', 'timezone'):
        if _has_column('tenants', col):
            op.drop_column('tenants', col)
