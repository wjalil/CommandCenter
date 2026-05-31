"""Add clock_in_lat/lng to time_entries for geofence soft mode

Revision ID: 20260531_geofence
Revises: 20260531_drop_is_produce
Create Date: 2026-05-31
"""
from typing import Union, Sequence
from alembic import op
import sqlalchemy as sa

revision: str = '20260531_geofence'
down_revision: Union[str, Sequence[str], None] = '20260531_drop_is_produce'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('time_entries', sa.Column('clock_in_lat', sa.Numeric(9, 6), nullable=True))
    op.add_column('time_entries', sa.Column('clock_in_lng', sa.Numeric(9, 6), nullable=True))


def downgrade() -> None:
    op.drop_column('time_entries', 'clock_in_lng')
    op.drop_column('time_entries', 'clock_in_lat')
