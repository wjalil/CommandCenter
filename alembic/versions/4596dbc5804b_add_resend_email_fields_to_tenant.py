"""add resend email fields to tenant

Revision ID: 4596dbc5804b
Revises: ef069b86b427
Create Date: 2025-12-21 20:20:05.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4596dbc5804b'
down_revision: Union[str, Sequence[str], None] = 'ef069b86b427'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    """Add RESEND email integration fields to tenants table"""
    op.add_column("tenants", sa.Column("resend_api_key_encrypted", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("order_notification_email", sa.String(), nullable=True))
    op.add_column("tenants", sa.Column("from_email", sa.String(), nullable=True))
    op.add_column("tenants", sa.Column("enable_order_emails", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    """Remove RESEND email integration fields from tenants table"""
    op.drop_column("tenants", "enable_order_emails")
    op.drop_column("tenants", "from_email")
    op.drop_column("tenants", "order_notification_email")
    op.drop_column("tenants", "resend_api_key_encrypted")
