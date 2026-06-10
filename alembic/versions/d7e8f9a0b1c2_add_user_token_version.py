"""add users.token_version for stateless-session revocation

Bumped on every password change/reset; JWTs carry it as the ``ver`` claim and
are rejected on mismatch. server_default '0' backfills existing rows (and
matches the ``ver`` defaulted for tokens minted before the claim existed, so
live sessions survive the upgrade until the first password change).

Revision ID: d7e8f9a0b1c2
Revises: c4dbc62ca2a9
Create Date: 2026-06-10 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "4f913b93ef9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "token_version")
