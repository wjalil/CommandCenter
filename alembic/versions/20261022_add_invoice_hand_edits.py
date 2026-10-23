"""editable Daily Delivery Invoices

- catering_invoices.edited_at / edited_by_user_id: set when someone edits an
  invoice's meal lines by hand. An edited draft stops following the kitchen
  (Produce card, counts, subs) until "Reset from kitchen" clears it.

Supplies (spoons, sporks...) are ordinary catering_invoice_lines rows with
meal_slot = 'supplies' — no schema change needed for them.

Idempotent: skips columns that already exist.

Revision ID: 20261022_invoice_edits
Revises: 20261001_payroll
Create Date: 2026-10-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20261022_invoice_edits'
down_revision: Union[str, Sequence[str], None] = '20261001_payroll'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if not _has_column('catering_invoices', 'edited_at'):
        op.add_column('catering_invoices', sa.Column('edited_at', sa.DateTime(), nullable=True))
    if not _has_column('catering_invoices', 'edited_by_user_id'):
        op.add_column('catering_invoices', sa.Column('edited_by_user_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('catering_invoices', 'edited_by_user_id')
    op.drop_column('catering_invoices', 'edited_at')
