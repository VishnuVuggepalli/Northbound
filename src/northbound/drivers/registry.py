"""Driver registry — maps ``platform_id`` -> driver class.

Drivers register themselves via the :func:`register` class decorator.
Importing the driver module is enough to populate the registry.
"""

from __future__ import annotations

from northbound.drivers.base import Driver

_REGISTRY: dict[str, type[Driver]] = {}


def register(cls: type[Driver]) -> type[Driver]:
    """Class decorator to register a driver under its ``platform_id``."""
    if cls.platform_id in _REGISTRY:
        raise ValueError(f"platform_id already registered: {cls.platform_id}")
    _REGISTRY[cls.platform_id] = cls
    return cls


def get_driver_class(platform_id: str) -> type[Driver]:
    if platform_id not in _REGISTRY:
        raise KeyError(f"unknown platform_id: {platform_id}")
    return _REGISTRY[platform_id]


def all_platforms() -> dict[str, type[Driver]]:
    """Snapshot of the current registry (defensive copy)."""
    return dict(_REGISTRY)


def _clear_for_tests() -> None:
    """Test-only: wipe the registry. Never call from app code."""
    _REGISTRY.clear()
