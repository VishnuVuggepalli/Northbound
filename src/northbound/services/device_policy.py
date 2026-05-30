"""Read-only policy enforcement — defense in depth for config writes.

``assert_writable`` is the single chokepoint that future write endpoints
(port edit, apply change) call before mutating a device. It blocks writes to:

* devices whose role is intrinsically read-only (``router`` / ``vpn`` — these
  carry traffic Northbound must never reconfigure), and
* devices on a platform whose driver declares ``capabilities.writable=False``
  (e.g. SwOS, FreeBSD — read-only forever).

It does NOT block *registration* of such devices: onboarding a read-only
router is a legitimate, supported flow. This guard only protects the
config-write path.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from northbound.drivers.registry import get_driver_class
from northbound.models.device import Device
from northbound.models.enums import DeviceRole

# Roles that must never accept a config write, regardless of platform.
_READ_ONLY_ROLES: frozenset[DeviceRole] = frozenset({DeviceRole.ROUTER, DeviceRole.VPN})

READ_ONLY_DEVICE_CODE = "READ_ONLY_DEVICE"


def _read_only_reason(device: Device) -> str | None:
    """Return a human reason if the device is read-only, else ``None``."""
    if device.role in _READ_ONLY_ROLES:
        return f"role {device.role.value!r} is read-only"
    try:
        driver_cls = get_driver_class(device.platform)
    except KeyError:
        # Unknown platform → treat as non-writable (fail closed).
        return f"unknown platform {device.platform!r}"
    if not driver_cls.capabilities.writable:
        return f"platform {device.platform!r} is read-only"
    return None


def is_writable(device: Device) -> bool:
    """True if config writes to ``device`` are permitted by policy."""
    return _read_only_reason(device) is None


def assert_writable(device: Device) -> None:
    """Raise 403 (code READ_ONLY_DEVICE) if ``device`` rejects config writes."""
    reason = _read_only_reason(device)
    if reason is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": READ_ONLY_DEVICE_CODE, "message": f"Device is read-only: {reason}"},
        )
