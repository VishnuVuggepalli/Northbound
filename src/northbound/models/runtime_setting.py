"""RuntimeSetting — admin-tunable runtime knobs (key/value).

A small catalog of operational settings an admin can change from the UI without
a redeploy or env change (e.g. the write-endpoint rate limit). Read paths use an
in-memory cache (see ``services.runtime_settings``); this table is the durable
source of truth that seeds the cache at startup.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from northbound.db import Base
from northbound.models._columns import created_at_col


class RuntimeSetting(Base):
    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    updated_at: Mapped[dt.datetime] = created_at_col()
    # User id of the admin who last changed it (nullable for seed rows).
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
