"""ChangeRequestEvent model — append-only state-machine transition log.

One row per status transition on a ChangeRequest. The reconciler replays
these on recovery to understand how a request reached its current state.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from northbound.db import Base
from northbound.models._columns import created_at_col, uuid_pk


class ChangeRequestEvent(Base):
    __tablename__ = "change_request_events"

    id: Mapped[str] = uuid_pk()
    request_id: Mapped[str] = mapped_column(
        ForeignKey("change_requests.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str] = mapped_column(String(64), nullable=False)
    to_status: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = created_at_col()
