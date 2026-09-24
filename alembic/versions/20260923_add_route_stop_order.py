"""split catering route codes into route + stop order

catering_programs.route_code used to hold both the route and the stop position
("R1-4"), so inserting a stop meant retyping every code after it. The position
now lives in its own column (route_stop_order), set by dragging stops on the
Route Board; route_code keeps just the route ("R1"). Existing "R1-4" style codes
are split here. Codes whose suffix isn't a number are left untouched.

Revision ID: 20260923_route_stop_order
Revises: 20260921_daily_counts
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260923_route_stop_order'
down_revision: Union[str, Sequence[str], None] = '20260921_daily_counts'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('catering_programs', sa.Column('route_stop_order', sa.Integer(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, route_code FROM catering_programs WHERE route_code LIKE '%-%'"
    )).fetchall()
    for program_id, route_code in rows:
        route, _, suffix = route_code.partition("-")
        suffix = suffix.strip()
        if route.strip() and suffix.isdigit():
            conn.execute(
                sa.text("UPDATE catering_programs SET route_code = :route, route_stop_order = :stop WHERE id = :id"),
                {"route": route.strip(), "stop": int(suffix), "id": program_id},
            )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, route_code, route_stop_order FROM catering_programs "
        "WHERE route_code IS NOT NULL AND route_stop_order IS NOT NULL"
    )).fetchall()
    for program_id, route_code, stop in rows:
        conn.execute(
            sa.text("UPDATE catering_programs SET route_code = :code WHERE id = :id"),
            {"code": f"{route_code}-{stop}", "id": program_id},
        )
    op.drop_column('catering_programs', 'route_stop_order')
