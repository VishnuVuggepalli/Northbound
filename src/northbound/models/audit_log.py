"""AuditLog model — append-only, tamper-evident action log.

``before``/``after`` capture state deltas as JSON but NEVER plaintext
credentials (cred actions record the action name only). ``row_hash`` /
``prev_hash`` form a hash chain; the chaining logic lands in the services
wave — the columns exist here so the schema is stable.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from northbound.db import Base
from northbound.models._columns import created_at_col, uuid_pk


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_device_id: Mapped[str | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    target_port: Mapped[str | None] = mapped_column(String(128), nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = created_at_col()
