"""ConfigBackup model — a captured running-config snapshot for a device.

The (device_id, fetched_at desc) index serves the common "latest backup"
and "backup history" queries.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from northbound.db import Base
from northbound.models._columns import uuid_pk


class ConfigBackup(Base):
    __tablename__ = "config_backups"
    __table_args__ = (Index("ix_config_backups_device_fetched", "device_id", "fetched_at"),)

    id: Mapped[str] = uuid_pk()
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    config_text: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_by: Mapped[str] = mapped_column(String(128), nullable=False)
