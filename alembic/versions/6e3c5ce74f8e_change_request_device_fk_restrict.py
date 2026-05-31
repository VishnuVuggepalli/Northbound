"""change_request.device_id FK CASCADE -> RESTRICT (retain compliance trail)

Revision ID: 6e3c5ce74f8e
Revises: abf3c6c84bf9
Create Date: 2026-05-31 00:00:00.000000

Deleting a device must NOT cascade-destroy its change-request history (the
compliance trail). This migration recreates the change_requests.device_id
foreign key with ON DELETE RESTRICT (upgrade) so a device with change-request
history cannot be hard-deleted, and back to ON DELETE CASCADE (downgrade).

SQLite cannot ALTER a constraint in place, so batch_alter_table recreates the
table. ``copy_from`` supplies a fully-specified Table (all columns + exactly one
device_id FK), which fully REPLACES the reflected schema — without it,
``table_args`` would *append* a second FK rather than swap the existing one.
The FK is named (fk_change_requests_device_id_devices) so it is deterministic
across the round-trip.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6e3c5ce74f8e"
down_revision: str | Sequence[str] | None = "abf3c6c84bf9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAME = "fk_change_requests_device_id_devices"


def _change_requests_table(metadata: sa.MetaData, ondelete: str) -> sa.Table:
    """Build the full change_requests Table with the device_id FK ondelete given.

    Mirrors the live model column set so ``copy_from`` replaces the reflected
    table definition wholesale (carrying data across via INSERT ... SELECT).
    """
    return sa.Table(
        "change_requests",
        metadata,
        sa.Column("id", sa.VARCHAR(length=36), primary_key=True, nullable=False),
        sa.Column("device_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("port_name", sa.VARCHAR(length=128), nullable=False),
        sa.Column("requested_by", sa.VARCHAR(length=128), nullable=False),
        sa.Column("requested_changes", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.VARCHAR(length=16), nullable=False),
        sa.Column("reviewer_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("reviewer_comment", sa.Text(), nullable=True),
        sa.Column("device_state_fingerprint", sa.VARCHAR(length=128), nullable=True),
        sa.Column("confirm_token", sa.VARCHAR(length=128), nullable=True),
        sa.Column("confirm_deadline_at", sa.Float(), nullable=True),
        sa.Column("diff_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "version_id",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=_FK_NAME,
            ondelete=ondelete,
        ),
    )


def _recreate_fk(ondelete: str) -> None:
    """Recreate change_requests with device_id FK using the given ondelete rule."""
    metadata = sa.MetaData()
    with op.batch_alter_table(
        "change_requests",
        schema=None,
        copy_from=_change_requests_table(metadata, ondelete),
        recreate="always",
    ):
        pass


def upgrade() -> None:
    """Upgrade schema: device_id FK -> ON DELETE RESTRICT."""
    _recreate_fk("RESTRICT")


def downgrade() -> None:
    """Downgrade schema: device_id FK -> ON DELETE CASCADE."""
    _recreate_fk("CASCADE")
