"""link catering routes to the delivery module

Three nullable link columns so catering and delivery share one route system
instead of two parallel ones:
- delivery_stops.catering_program_id — a delivery stop that mirrors a catering
  program (kept in sync from the program, so a school is entered once)
- delivery_route_templates.catering_route_code — the template whose weekday
  drivers and pay rates run that catering route (e.g. "R1")
- delivery_routes.catering_manifest_id — the daily delivery route created from
  a released catering manifest

Revision ID: 20260923b_catering_delivery
Revises: 20260923_route_stop_order
Create Date: 2026-09-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260923b_catering_delivery'
down_revision: Union[str, Sequence[str], None] = '20260923_route_stop_order'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('delivery_stops', sa.Column('catering_program_id', sa.String(), nullable=True))
    op.create_foreign_key(
        'fk_delivery_stops_catering_program', 'delivery_stops', 'catering_programs',
        ['catering_program_id'], ['id'], ondelete='SET NULL',
    )
    op.create_unique_constraint('uq_delivery_stops_catering_program', 'delivery_stops', ['catering_program_id'])

    op.add_column('delivery_route_templates', sa.Column('catering_route_code', sa.String(), nullable=True))
    op.create_unique_constraint(
        'uq_route_template_catering_route', 'delivery_route_templates', ['tenant_id', 'catering_route_code'],
    )

    op.add_column('delivery_routes', sa.Column('catering_manifest_id', sa.String(), nullable=True))
    op.create_foreign_key(
        'fk_delivery_routes_catering_manifest', 'delivery_routes', 'catering_daily_manifests',
        ['catering_manifest_id'], ['id'], ondelete='SET NULL',
    )
    op.create_unique_constraint('uq_delivery_routes_catering_manifest', 'delivery_routes', ['catering_manifest_id'])


def downgrade() -> None:
    op.drop_constraint('uq_delivery_routes_catering_manifest', 'delivery_routes', type_='unique')
    op.drop_constraint('fk_delivery_routes_catering_manifest', 'delivery_routes', type_='foreignkey')
    op.drop_column('delivery_routes', 'catering_manifest_id')

    op.drop_constraint('uq_route_template_catering_route', 'delivery_route_templates', type_='unique')
    op.drop_column('delivery_route_templates', 'catering_route_code')

    op.drop_constraint('uq_delivery_stops_catering_program', 'delivery_stops', type_='unique')
    op.drop_constraint('fk_delivery_stops_catering_program', 'delivery_stops', type_='foreignkey')
    op.drop_column('delivery_stops', 'catering_program_id')
