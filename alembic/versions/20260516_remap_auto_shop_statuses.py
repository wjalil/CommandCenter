"""remap_auto_shop_statuses

Revision ID: 20260516_remap_statuses
Revises: 20260506_auto_shop
Create Date: 2026-05-16

Renames old status slugs to the client's workflow:
  intake / diagnosing            → new_arrival
  waiting_on_adjuster            → waiting_for_adjuster
  adjuster_approved              → waiting_for_parts
  waiting_on_parts               → waiting_for_parts
  parts_received                 → disassemble
  in_progress                    → body_work
  completed                      → complete
  ready_for_pickup               → ready_for_pickup  (unchanged)
"""
from typing import Sequence, Union
from alembic import op

revision: str = "20260516_remap_statuses"
down_revision: Union[str, None] = "20260506_auto_shop"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TO_NEW = {
    "intake": "new_arrival",
    "diagnosing": "new_arrival",
    "waiting_on_adjuster": "waiting_for_adjuster",
    "adjuster_approved": "waiting_for_parts",
    "waiting_on_parts": "waiting_for_parts",
    "parts_received": "disassemble",
    "in_progress": "body_work",
    "completed": "complete",
}


def _remap(table: str, column: str) -> None:
    conn = op.get_bind()
    for old, new in OLD_TO_NEW.items():
        conn.execute(
            f"UPDATE {table} SET {column} = '{new}' WHERE {column} = '{old}'"  # noqa: S608
        )


def upgrade() -> None:
    _remap("repair_orders", "status")
    _remap("repair_order_status_logs", "old_status")
    _remap("repair_order_status_logs", "new_status")


def downgrade() -> None:
    pass  # one-way migration; old slugs are gone
