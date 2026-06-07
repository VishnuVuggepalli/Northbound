"""sites catalog: free-form site slugs replace the fixed lab/dc enum

Revision ID: b1f2a3c4d5e6
Revises: 6e3c5ce74f8e
Create Date: 2026-06-02 00:00:00.000000

The device "environment" was a closed Enum('lab','dc'). Sites are now a
runtime-managed catalog (the ``sites`` table), and ``devices.environment`` is a
free-form slug string referencing ``sites.slug`` (a soft reference, mirroring
``devices.platform``). This migration:

  upgrade
    1. create the ``sites`` table
    2. seed the two original environments as default sites (Lab, Datacenter)
    3. relax ``devices.environment`` from Enum('lab','dc') to String(64)

  downgrade
    1. re-tighten ``devices.environment`` to Enum('lab','dc')
       (rows with a non lab/dc slug would violate the enum — acceptable, this
        is a lossy reversal of a feature that allowed arbitrary sites)
    2. drop the ``sites`` table

SQLite cannot ALTER a column type in place, so ``batch_alter_table`` recreates
the table (carrying data across) and drops the old CHECK constraint that backed
the enum.
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1f2a3c4d5e6"
down_revision: str | Sequence[str] | None = "6e3c5ce74f8e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The two original environments, preserved as default sites.
_DEFAULT_SITES: tuple[tuple[str, str], ...] = (("lab", "Lab"), ("dc", "Datacenter"))

_ENV_ENUM = sa.Enum("lab", "dc", name="environment")


def upgrade() -> None:
    sites = op.create_table(
        "sites",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_sites_slug"),
    )
    op.bulk_insert(
        sites,
        [{"id": str(uuid4()), "slug": slug, "name": name} for slug, name in _DEFAULT_SITES],
    )

    # Relax the enum to a free-form string. batch mode rebuilds the table on
    # SQLite and drops the enum CHECK constraint.
    with op.batch_alter_table("devices") as batch:
        batch.alter_column(
            "environment",
            existing_type=_ENV_ENUM,
            type_=sa.String(length=64),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.alter_column(
            "environment",
            existing_type=sa.String(length=64),
            type_=_ENV_ENUM,
            existing_nullable=False,
        )
    op.drop_table("sites")
