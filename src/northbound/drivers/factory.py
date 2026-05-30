"""Driver factory — build a :class:`Driver` instance from runtime data.

The registry maps ``platform_id -> driver class``; this thin layer turns a
persisted :class:`~northbound.models.device.Device` (or raw wizard params)
plus decrypted :class:`~northbound.schemas.driver.Credentials` into a live
driver. Keeping it separate from the registry avoids the API layer reaching
into ``get_driver_class`` and re-deriving ``ConnectionParams`` everywhere.
"""

from __future__ import annotations

from northbound.drivers.base import Driver
from northbound.drivers.registry import get_driver_class
from northbound.models.device import Device
from northbound.schemas.driver import ConnectionParams, Credentials


def driver_from_params(
    platform_id: str,
    conn: ConnectionParams,
    creds: Credentials,
) -> Driver:
    """Instantiate the driver registered under ``platform_id``.

    Raises ``KeyError`` (from the registry) if the platform is unknown.
    """
    cls = get_driver_class(platform_id)
    return cls(conn, creds)


def driver_for(
    device: Device,
    creds: Credentials,
    *,
    timeout_seconds: float = 10.0,
) -> Driver:
    """Instantiate the driver for a persisted device with decrypted creds."""
    conn = ConnectionParams(
        host=device.mgmt_ip,
        port=None,
        prefer_native_api=device.prefer_native_api,
        timeout_seconds=timeout_seconds,
    )
    return driver_from_params(device.platform, conn, creds)
