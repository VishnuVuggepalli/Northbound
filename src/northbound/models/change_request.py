"""ChangeRequest model — the workflow record for a proposed port change.

Status moves through a state machine (see ChangeRequestEvent for the
transition log). Durability fields (``confirm_deadline_at``,
``device_state_fingerprint``) let the reconciler recover an in-flight apply
after a process restart.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from northbound.db import Base
from northbound.models._columns import created_at_col, str_enum, uuid_pk
from northbound.models.enums import ChangeRequestStatus


class ChangeRequest(Base):
    __tablename__ = "change_requests"

    # Optimistic-concurrency version counter. SQLAlchemy auto-increments this on
    # every UPDATE and raises StaleDataError if a concurrent transaction bumped
    # the row since it was loaded. Portable across SQLite (v1) and Postgres —
    # unlike ``SELECT ... FOR UPDATE``, which SQLite does not meaningfully honour.
    # This is the backstop behind the atomic conditional status UPDATE used as
    # the authoritative claim guard in the apply/confirm flows (CON-1/CON-2).
    version_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": version_id}

    id: Mapped[str] = uuid_pk()
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    port_name: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    # JSON-serialized PortChange payload. dict[str, object]-shaped at the
    # boundary; SQLAlchemy's JSON type round-trips it as-is.
    requested_changes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[ChangeRequestStatus] = mapped_column(
        str_enum(ChangeRequestStatus, name="change_request_status"),
        nullable=False,
        default=ChangeRequestStatus.PENDING,
    )
    reviewer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewer_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_state_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirm_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirm_deadline_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    diff_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = created_at_col()
    # Liveness heartbeat: server-stamped on insert and bumped on every UPDATE.
    # The reconciler's stale-apply detector (CON-3) reads this so a genuinely
    # slow-but-live apply that emits no intervening transition event still looks
    # alive (the apply flow touches it just before the long ``apply_change``).
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
