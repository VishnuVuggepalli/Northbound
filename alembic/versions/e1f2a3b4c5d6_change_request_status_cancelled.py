"""add change_request_status 'cancelled' (+ backfill 'needs_revision')

Soft-delete sink for withdrawn requests. SQLite stores ``status`` as a plain
string (SAEnum's ``create_constraint`` defaults False since SQLAlchemy 1.4) so
no schema change is needed there — this migration is a no-op on SQLite. On
PostgreSQL ``status`` is a native ENUM type, so a new label must be added with
``ALTER TYPE ... ADD VALUE``. ``needs_revision`` was added to the Python enum
without a migration, so we backfill it here too for parity on PG deployments.

Revision ID: e1f2a3b4c5d6
Revises: d7e8f9a0b1c2
Create Date: 2026-06-11 19:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Labels the running Python enum carries that a pre-existing PG enum type may be
# missing. Hardcoded constants (no user input) — safe to interpolate.
_NEW_VALUES = ("needs_revision", "cancelled")


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite/others: status is a plain string column — nothing to alter.
        return
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on older PG;
    # AUTOCOMMIT sidesteps that. IF NOT EXISTS keeps it idempotent/re-runnable.
    autocommit = bind.execution_options(isolation_level="AUTOCOMMIT")
    for value in _NEW_VALUES:
        autocommit.exec_driver_sql(
            f"ALTER TYPE change_request_status ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade() -> None:
    """Downgrade schema.

    PostgreSQL cannot DROP a single value from an enum type without recreating
    the type and rewriting every dependent column — disproportionate and risky
    for a label that is simply unused after a revert. Intentional no-op.
    """
    pass
