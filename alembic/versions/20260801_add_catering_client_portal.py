"""add catering client portal tables (client accounts, portal requests)

Revision ID: 20260801_client_portal
Revises: 6d01097f1887
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260801_client_portal'
down_revision: Union[str, Sequence[str], None] = '6d01097f1887'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Additive only — creates two new tables, touches nothing existing."""
    op.create_table(
        'catering_client_accounts',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('program_id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('invite_token', sa.String(), nullable=True),
        sa.Column('invite_token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('invite_sent_at', sa.DateTime(), nullable=True),
        sa.Column('reset_token', sa.String(), nullable=True),
        sa.Column('reset_token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['program_id'], ['catering_programs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('program_id', name='uq_client_account_program'),
        sa.UniqueConstraint('invite_token'),
        sa.UniqueConstraint('reset_token'),
    )
    op.create_index('idx_client_accounts_tenant', 'catering_client_accounts', ['tenant_id'], unique=False)

    op.create_table(
        'client_portal_requests',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('program_id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('client_account_id', sa.String(), nullable=True),
        sa.Column('request_type', sa.String(), nullable=False, server_default='general'),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('proposed_counts', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='open'),
        sa.Column('staff_reply', sa.Text(), nullable=True),
        sa.Column('resolved_by_user_id', sa.String(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['program_id'], ['catering_programs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['client_account_id'], ['catering_client_accounts.id']),
        sa.ForeignKeyConstraint(['resolved_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_portal_requests_tenant', 'client_portal_requests', ['tenant_id'], unique=False)
    op.create_index('idx_portal_requests_program', 'client_portal_requests', ['program_id'], unique=False)
    op.create_index('idx_portal_requests_status', 'client_portal_requests', ['tenant_id', 'status'], unique=False)


def downgrade() -> None:
    """Downgrade schema. Drops only the two tables this migration created."""
    op.drop_index('idx_portal_requests_status', table_name='client_portal_requests')
    op.drop_index('idx_portal_requests_program', table_name='client_portal_requests')
    op.drop_index('idx_portal_requests_tenant', table_name='client_portal_requests')
    op.drop_table('client_portal_requests')

    op.drop_index('idx_client_accounts_tenant', table_name='catering_client_accounts')
    op.drop_table('catering_client_accounts')
