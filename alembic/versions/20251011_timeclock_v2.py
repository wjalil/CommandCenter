"""TimeClock v2: table, pay snapshot, constraints, unique-open index, user.hourly_rate"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

# Revision identifiers, used by Alembic.
revision = "20251011_timeclock_v2"
down_revision = "08c839ae49b6"
branch_labels = None
depends_on = None


def upgrade():
    # --- 1) Ensure enum type exists (Postgres) ---
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'timestatus') THEN
                CREATE TYPE timestatus AS ENUM ('OPEN','CLOSED','APPROVED','PAID');
            END IF;
        END$$;
        """
    )

    # --- 2) Create table time_entries ---
    op.create_table(
        "time_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),

        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("shift_id", sa.String(), sa.ForeignKey("shifts.id"), nullable=True, index=True),

        # store UTC timestamps (render to local at UI)
        sa.Column("clock_in", sa.DateTime(timezone=False), nullable=False),
        sa.Column("clock_out", sa.DateTime(timezone=False), nullable=True),

        # ✅ Use existing Postgres ENUM; do NOT try to create it again
        sa.Column(
            "status",
            PG_ENUM("OPEN", "CLOSED", "APPROVED", "PAID", name="timestatus", create_type=False),
            nullable=False,
            server_default="OPEN",
        ),

        sa.Column("notes", sa.String(), nullable=True),

        sa.Column("clock_in_source", sa.String(), nullable=True),
        sa.Column("clock_out_source", sa.String(), nullable=True),
        sa.Column("clock_in_ip", sa.String(), nullable=True),
        sa.Column("clock_out_ip", sa.String(), nullable=True),

        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("gross_pay", sa.Numeric(10, 2), nullable=True),

        sa.Column("is_seed", sa.Boolean(), server_default=sa.text("false"), nullable=False),

        sa.CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes >= 0",
            name="ck_time_entries_duration_nonneg",
        ),
        sa.CheckConstraint(
            "gross_pay IS NULL OR gross_pay >= 0",
            name="ck_time_entries_gross_nonneg",
        ),
    )

    # Helpful indexes
    op.create_index("ix_time_entries_user", "time_entries", ["user_id"])
    op.create_index("ix_time_entries_tenant", "time_entries", ["tenant_id"])
    op.create_index("ix_time_entries_status", "time_entries", ["status"])

    # --- 3) Add hourly_rate to users (idempotent) ---
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS hourly_rate NUMERIC(10,2);")

    # --- 4) Partial unique index to enforce one OPEN per (tenant_id, user_id) ---
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_open_entry_per_user
        ON time_entries (tenant_id, user_id)
        WHERE status = 'OPEN';
        """
    )


def downgrade():
    # Drop partial unique index (if exists)
    op.execute("DROP INDEX IF EXISTS uq_open_entry_per_user;")

    # Drop helper indexes
    op.drop_index("ix_time_entries_status", table_name="time_entries")
    op.drop_index("ix_time_entries_tenant", table_name="time_entries")
    op.drop_index("ix_time_entries_user", table_name="time_entries")

    # Drop table
    op.drop_table("time_entries")

    # Drop users.hourly_rate column (optional/conditional)
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS hourly_rate;")

    # Drop enum type if nothing else uses it
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'timestatus') THEN
                -- Only drop if no columns still depend on it
                PERFORM 1
                FROM information_schema.columns
                WHERE udt_name = 'timestatus';
                IF NOT FOUND THEN
                    DROP TYPE timestatus;
                END IF;
            END IF;
        END$$;
        """
    )
