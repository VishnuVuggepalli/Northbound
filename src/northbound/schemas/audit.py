"""Pydantic v2 DTOs for the audit API surface.

Reuses :class:`AuditEntryOut` from the port schema (single shape for an audit
row) and adds the list helper.
"""

from __future__ import annotations

from northbound.models.audit_log import AuditLog
from northbound.schemas.port import AuditEntryOut


def audit_entry_out(row: AuditLog) -> AuditEntryOut:
    """Project an AuditLog row to its public DTO."""
    return AuditEntryOut(
        id=row.id,
        user_id=row.user_id,
        action=row.action,
        target_device_id=row.target_device_id,
        target_port=row.target_port,
        before=row.before,
        after=row.after,
        result=row.result,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )
