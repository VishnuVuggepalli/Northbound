"""Audit router — read-only, filtered audit-log access.

The audit log is append-only and hash-chained (principal-engineering D6); this
router only reads it. ADMIN-only: the full log exposes every config change's
before/after, device inventory, and per-user activity (and the ``?user=``
filter would let a requester enumerate user IDs). Requesters still see the
narrow slices that concern them — per-port history rides the port-detail
endpoint, and their own requests carry their event timeline.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.api.deps import require_admin
from northbound.db import get_session
from northbound.models.audit_log import AuditLog
from northbound.models.user import User
from northbound.schemas.audit import audit_entry_out
from northbound.schemas.port import AuditEntryOut

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditEntryOut])
async def list_audit(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    device_id: str | None = None,
    port: str | None = None,
    user: str | None = None,
    limit: int = 200,
) -> list[AuditEntryOut]:
    """Filtered audit list, newest first (``?device_id=&port=&user=``)."""
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if device_id is not None:
        stmt = stmt.where(AuditLog.target_device_id == device_id)
    if port is not None:
        stmt = stmt.where(AuditLog.target_port == port)
    if user is not None:
        stmt = stmt.where(AuditLog.user_id == user)
    stmt = stmt.limit(max(1, min(limit, 1000)))
    rows = await session.scalars(stmt)
    return [audit_entry_out(r) for r in rows.all()]
