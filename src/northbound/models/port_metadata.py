"""PortMetadata model — human-authored fields layered onto a live port.

A port is identified by (device_id, port_name); that pair is unique. The
``last_human_edit_*`` columns let the UI flag drift between operator intent
and live device state.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from northbound.db import Base
from northbound.models._columns import uuid_pk


class PortMetadata(Base):
    __tablename__ = "port_metadata"
    __table_args__ = (
        UniqueConstraint("device_id", "port_name", name="uq_port_metadata_device_port"),
    )

    id: Mapped[str] = uuid_pk()
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    port_name: Mapped[str] = mapped_column(String(128), nullable=False)
    host_model: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    bmc_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_human_edit_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_human_edit_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
