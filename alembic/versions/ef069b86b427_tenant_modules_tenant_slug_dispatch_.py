"""tenant modules + tenant slug/dispatch phone

Revision ID: ef069b86b427
Revises: 1a723daceeeb
Create Date: 2025-12-15 20:54:51.927237

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ef069b86b427'
down_revision: Union[str, Sequence[str], None] = '1a723daceeeb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column("tenants", sa.Column("slug", sa.String(), nullable=True))
    op.add_column("tenants", sa.Column("dispatch_phone", sa.String(), nullable=True))

    op.create_table(
        "tenant_modules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module_key", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("tenant_id", "module_key", name="uq_tenant_module_key"),
    )

    # Optional: backfill slug from name (safe default)
    # You can keep it simple now and fill manually per tenant if you prefer.