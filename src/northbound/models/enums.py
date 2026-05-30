"""Shared StrEnums backing the ORM ``Enum`` columns.

StrEnum members serialize to their string value, so the DB stores readable
strings (e.g. ``"admin"``) rather than opaque integers.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    REQUESTER = "requester"


class Environment(StrEnum):
    LAB = "lab"
    DC = "dc"


class DeviceRole(StrEnum):
    LEAF = "leaf"
    SPINE = "spine"
    ROUTER = "router"
    VPN = "vpn"


class ChangeRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLYING = "applying"
    AWAITING_CONFIRM = "awaiting_confirm"
    APPLIED = "applied"
    FAILED = "failed"
    REVERTED = "reverted"
