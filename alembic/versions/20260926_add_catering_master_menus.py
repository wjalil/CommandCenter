"""add catering master menus

A tenant-wide master menu per month (usually uploaded from a CSV) that gets
published into every program's monthly menu, instead of building one menu per
program by hand.
- catering_master_menus / _days / _components — the master menu itself
- catering_monthly_menus.master_menu_id — which master menu a program menu was published from
- catering_menu_days.is_customized — the day was edited by hand for that program,
  so a re-publish of the master menu leaves it alone

Revision ID: 20260926_master_menus
Revises: 20260923b_catering_delivery
Create Date: 2026-09-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '20260926_master_menus'
down_revision: Union[str, Sequence[str], None] = '20260923b_catering_delivery'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The app's startup create_all() may already have made the new tables (it can't add
# columns to existing ones), so every step checks first.

def _inspector():
    return inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return _inspector().has_table(name)


def _col_exists(table: str, column: str) -> bool:
    return any(c["name"] == column for c in _inspector().get_columns(table))


def _index_exists(table: str, index_name: str) -> bool:
    return any(i["name"] == index_name for i in _inspector().get_indexes(table))


def _fk_exists(table: str, column: str) -> bool:
    return any(fk["constrained_columns"] == [column] for fk in _inspector().get_foreign_keys(table))


def upgrade() -> None:
    if not _table_exists('catering_master_menus'):
        op.create_table(
            'catering_master_menus',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('month', sa.Integer(), nullable=False),
            sa.Column('year', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='draft'),
            sa.Column('source_filename', sa.String(), nullable=True),
            sa.Column('published_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('tenant_id', 'name', 'month', 'year', name='uq_master_menu'),
        )
    if not _index_exists('catering_master_menus', 'idx_master_menus_tenant'):
        op.create_index('idx_master_menus_tenant', 'catering_master_menus', ['tenant_id', 'year', 'month'])

    if not _table_exists('catering_master_menu_days'):
        op.create_table(
            'catering_master_menu_days',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('master_menu_id', sa.String(), sa.ForeignKey('catering_master_menus.id', ondelete='CASCADE'), nullable=False),
            sa.Column('service_date', sa.Date(), nullable=False),
            sa.Column('is_closed', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('closed_reason', sa.String(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.UniqueConstraint('master_menu_id', 'service_date', name='uq_master_menu_day'),
        )

    if not _table_exists('catering_master_menu_components'):
        op.create_table(
            'catering_master_menu_components',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('day_id', sa.String(), sa.ForeignKey('catering_master_menu_days.id', ondelete='CASCADE'), nullable=False),
            sa.Column('component_id', sa.Integer(), sa.ForeignKey('food_components.id'), nullable=False),
            sa.Column('meal_slot', sa.String(), nullable=False),
            sa.Column('is_vegan', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
            sa.UniqueConstraint('day_id', 'component_id', 'meal_slot', 'is_vegan', name='uq_master_menu_component'),
        )
    if not _index_exists('catering_master_menu_components', 'idx_master_menu_components_day'):
        op.create_index('idx_master_menu_components_day', 'catering_master_menu_components', ['day_id'])

    if not _col_exists('catering_monthly_menus', 'master_menu_id'):
        op.add_column('catering_monthly_menus', sa.Column('master_menu_id', sa.String(), nullable=True))
    if not _fk_exists('catering_monthly_menus', 'master_menu_id'):
        op.create_foreign_key(
            'fk_monthly_menus_master_menu', 'catering_monthly_menus', 'catering_master_menus',
            ['master_menu_id'], ['id'], ondelete='SET NULL',
        )
    if not _col_exists('catering_menu_days', 'is_customized'):
        op.add_column(
            'catering_menu_days',
            sa.Column('is_customized', sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    op.drop_column('catering_menu_days', 'is_customized')
    op.drop_constraint('fk_monthly_menus_master_menu', 'catering_monthly_menus', type_='foreignkey')
    op.drop_column('catering_monthly_menus', 'master_menu_id')
    op.drop_index('idx_master_menu_components_day', table_name='catering_master_menu_components')
    op.drop_table('catering_master_menu_components')
    op.drop_table('catering_master_menu_days')
    op.drop_index('idx_master_menus_tenant', table_name='catering_master_menus')
    op.drop_table('catering_master_menus')
