"""Shared StrEnums backing the ORM ``Enum`` columns.

StrEnum members serialize to their string value, so the DB stores readable
strings (e.g. ``"admin"``) rather than opaque integers.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    REQUESTER = "requester"


# NOTE: a device's site (formerly the fixed "environment" enum of lab/dc) is now
# a free-form slug string referencing the runtime-managed ``sites`` catalog
# (see northbound.models.site.Site) — mirroring how ``platform`` is a free-form
# string backed by the platforms catalog. Admins add sites at runtime; no enum,
# no migration per new site.


class DeviceRole(StrEnum):
    LEAF = "leaf"
    SPINE = "spine"
    ROUTER = "router"
    VPN = "vpn"


class ChangeRequestStatus(StrEnum):
    PENDING = "pending"
    # Admin asked the requester to revise (non-terminal): the requester edits and
    # resubmits → back to PENDING. The collaborative alternative to a hard reject.
    NEEDS_REVISION = "needs_revision"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLYING = "applying"
    AWAITING_CONFIRM = "awaiting_confirm"
    APPLIED = "applied"
    FAILED = "failed"
    REVERTED = "reverted"
    # Soft delete: the requester (own) or an admin withdrew the request before it
    # was applied. Terminal, and the row + its event history are retained so the
    # audit/compliance trail stays intact (we never hard-delete a request).
    CANCELLED = "cancelled"
