"""add cacfp_eligible flag to catering programs

Revision ID: 20260827_cacfp_eligible
Revises: 20260801_client_portal
Create Date: 2026-08-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260827_cacfp_eligible'
down_revision: Union[str, Sequence[str], None] = '20260801_client_portal'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Additive only — one new column on catering_programs."""
    op.add_column(
        'catering_programs',
        sa.Column('cacfp_eligible', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('catering_programs', 'cacfp_eligible')
