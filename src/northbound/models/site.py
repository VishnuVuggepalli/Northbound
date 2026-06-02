"""Site model — a managed location/environment a device lives in.

Replaces the old fixed ``Environment`` enum (lab/dc). A site is a runtime-managed
catalog row: admins create new sites without a code change or migration, exactly
like the platforms catalog. A device references its site by ``slug`` (a free-form
string on ``Device.environment``), not a hard FK — mirroring the soft
``Device.platform`` reference. Referential safety is enforced at the API layer
(a site with attached devices cannot be deleted).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from northbound.db import Base
from northbound.models._columns import created_at_col, uuid_pk


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[str] = uuid_pk()
    # URL-safe stable identifier (used in routes like /env/<slug>). Immutable.
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Human-readable display name (e.g. "Lab", "Datacenter", "Edge DR").
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[dt.datetime] = created_at_col()
