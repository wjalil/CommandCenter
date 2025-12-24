"""add_tenant_pin_unique_constraints (FIXED VERSION)

Revision ID: 6b01f7a6ab52
Revises: ac965a8dc934
Create Date: 2025-12-21 23:08:34.547907

CRITICAL FIX: Original version incorrectly dropped time_entries and daily_tasks tables.
This version ONLY adds the unique constraints as intended.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '6b01f7a6ab52'
down_revision: Union[str, Sequence[str], None] = 'ac965a8dc934'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - ONLY add unique constraints."""
    # Add unique constraint to customers table (tenant_id + pin_code)
    op.create_unique_constraint('uq_customer_tenant_pin', 'customers', ['tenant_id', 'pin_code'])

    # Add unique constraint to users table (tenant_id + pin_code)
    op.create_unique_constraint('uq_user_tenant_pin', 'users', ['tenant_id', 'pin_code'])


def downgrade() -> None:
    """Downgrade schema - remove unique constraints."""
    op.drop_constraint('uq_user_tenant_pin', 'users', type_='unique')
    op.drop_constraint('uq_customer_tenant_pin', 'customers', type_='unique')
