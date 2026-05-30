"""ORM models package.

Re-exports every mapped class so ``Base.metadata`` is fully populated by a
single ``import northbound.models`` (Alembic autogenerate and test setup
both rely on this).
"""

from __future__ import annotations

from northbound.models.audit_log import AuditLog
from northbound.models.change_request import ChangeRequest
from northbound.models.change_request_event import ChangeRequestEvent
from northbound.models.config_backup import ConfigBackup
from northbound.models.device import Device
from northbound.models.enums import (
    ChangeRequestStatus,
    DeviceRole,
    Environment,
    UserRole,
)
from northbound.models.port_metadata import PortMetadata
from northbound.models.user import User

__all__ = [
    "AuditLog",
    "ChangeRequest",
    "ChangeRequestEvent",
    "ChangeRequestStatus",
    "ConfigBackup",
    "Device",
    "DeviceRole",
    "Environment",
    "PortMetadata",
    "User",
    "UserRole",
]
