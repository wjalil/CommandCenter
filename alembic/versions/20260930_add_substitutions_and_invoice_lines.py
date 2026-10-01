"""production substitutions + frozen Daily Delivery Invoice lines

- catering_substitutions: same-day swaps made on the Production Sheet, layered
  over the planned menu (kitchen-wide or per program).
- catering_invoice_lines: what each invoice delivered, frozen at build time so a
  later menu edit can't rewrite a delivery record.
- catering_invoices: snapshot of the center (name/address/contact/service style),
  finalized_at / updated_at for the lock-on-release lifecycle, and an index on
  (program_id, service_date) — the key invoices are now built by.
- catering_programs.milk_type: the milk printed on the DDI ("1% Low-Fat Milk").

Existing invoices get their lines built the first time they're opened.

Idempotent: the app's startup create_all() may already have created the new
tables (it can't add columns to existing ones), so every step checks first.

Revision ID: 20260930_subs_ddi
Revises: 20260926_master_menus
Create Date: 2026-09-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260930_subs_ddi'
down_revision: Union[str, Sequence[str], None] = '20260926_master_menus'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in _inspector().get_columns(table))


def _has_index(table: str, index: str) -> bool:
    return any(i["name"] == index for i in _inspector().get_indexes(table))


def _add_column(table: str, column: sa.Column):
    if not _has_column(table, column.name):
        op.add_column(table, column)


def _create_index(name: str, table: str, columns: list):
    if not _has_index(table, name):
        op.create_index(name, table, columns)


def upgrade() -> None:
    if not _has_table('catering_substitutions'):
        op.create_table(
        'catering_substitutions',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('service_date', sa.Date(), nullable=False),
        sa.Column('meal_slot', sa.String(), nullable=True),
        sa.Column('is_vegan', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('program_id', sa.String(), sa.ForeignKey('catering_programs.id', ondelete='CASCADE'), nullable=True),
        sa.Column('original_component_id', sa.Integer(), sa.ForeignKey('food_components.id'), nullable=False),
        sa.Column('replacement_component_id', sa.Integer(), sa.ForeignKey('food_components.id'), nullable=False),
        sa.Column('portion_oz', sa.Numeric(5, 2), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.String(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        )
    _create_index('idx_substitutions_tenant_date', 'catering_substitutions', ['tenant_id', 'service_date'])

    if not _has_table('catering_invoice_lines'):
        op.create_table(
        'catering_invoice_lines',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('invoice_id', sa.String(), sa.ForeignKey('catering_invoices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('meal_slot', sa.String(), nullable=False),
        sa.Column('is_vegan', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('meal_count', sa.Integer(), nullable=False),
        sa.Column('component_type', sa.String(), nullable=True),
        sa.Column('item_name', sa.String(), nullable=False),
        sa.Column('portion_qty', sa.Numeric(7, 2), nullable=True),
        sa.Column('portion_unit', sa.String(), nullable=True),
        sa.Column('substituted_for', sa.String(), nullable=True),
        sa.Column('substitution_reason', sa.Text(), nullable=True),
        sa.Column('is_auto', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        )
    _create_index('idx_invoice_lines_invoice', 'catering_invoice_lines', ['invoice_id'])

    _add_column('catering_invoices', sa.Column('site_name', sa.String(), nullable=True))
    _add_column('catering_invoices', sa.Column('site_address', sa.Text(), nullable=True))
    _add_column('catering_invoices', sa.Column('client_name', sa.String(), nullable=True))
    _add_column('catering_invoices', sa.Column('service_style', sa.String(), nullable=True))
    _add_column('catering_invoices', sa.Column('is_cacfp', sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column('catering_invoices', sa.Column('finalized_at', sa.DateTime(), nullable=True))
    _add_column('catering_invoices', sa.Column('updated_at', sa.DateTime(), nullable=True))
    _create_index('idx_invoices_program_date', 'catering_invoices', ['program_id', 'service_date'])

    _add_column('catering_programs', sa.Column('milk_type', sa.String(), nullable=True))

    # Existing invoices: mark the CACFP ones so the Day Pack's CACFP filter finds them
    op.execute(
        "UPDATE catering_invoices SET is_cacfp = (SELECT p.cacfp_eligible FROM catering_programs p "
        "WHERE p.id = catering_invoices.program_id)"
    )


def downgrade() -> None:
    op.drop_column('catering_programs', 'milk_type')
    op.drop_index('idx_invoices_program_date', table_name='catering_invoices')
    for col in ('updated_at', 'finalized_at', 'is_cacfp', 'service_style', 'client_name', 'site_address', 'site_name'):
        op.drop_column('catering_invoices', col)
    op.drop_index('idx_invoice_lines_invoice', table_name='catering_invoice_lines')
    op.drop_table('catering_invoice_lines')
    op.drop_index('idx_substitutions_tenant_date', table_name='catering_substitutions')
    op.drop_table('catering_substitutions')
