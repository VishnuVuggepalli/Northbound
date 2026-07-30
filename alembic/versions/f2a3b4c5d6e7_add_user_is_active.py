"""add users.is_active so accounts can be disabled without being destroyed

Until now there was no way to remove OR disable an account: the users table had
no active flag and the API had no DELETE. On the lab node that left 9 accounts,
4 of them self-registered within 48 hours, all permanent.

Disable is the reversible lever and the one to reach for by default — a
disabled user keeps their history, which matters because audit rows and change
requests reference user ids. DELETE is for accounts that should never have
existed.

server_default true backfills every existing row, so the upgrade cannot lock
anyone out. Disabling also bumps ``token_version`` (see api/users.py), which is
what actually kills a live session — the flag alone would let an issued JWT
keep working until it expired.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-30 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Dropping the column re-enables every disabled account. That is the only
    # possible behaviour without a column to record the state, and is why the
    # note exists rather than a silent drop.
    op.drop_column("users", "is_active")
