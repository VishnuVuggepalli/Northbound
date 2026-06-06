"""Pydantic v2 DTOs for the change-requests API surface."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from northbound.models.change_request import ChangeRequest
from northbound.models.enums import ChangeRequestStatus
from northbound.schemas.driver import PortChange


class RequestCreateIn(BaseModel):
    """Body of ``POST /api/requests`` — file a change request."""

    device_id: str = Field(min_length=1, max_length=36)
    port_name: str = Field(min_length=1, max_length=128)
    requested_changes: PortChange
    reason: str = Field(default="", max_length=2000)


class RequestVlanIn(BaseModel):
    """Body of ``POST /api/requests/vlan`` — file a VLAN-database change."""

    device_id: str = Field(min_length=1, max_length=36)
    action: Literal["create", "delete"]
    vlan_id: int = Field(ge=1, le=4094)
    name: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    reason: str = Field(default="", max_length=2000)


class RequestL3In(BaseModel):
    """Body of ``POST /api/requests/l3`` — file a routed-interface change."""

    device_id: str = Field(min_length=1, max_length=36)
    action: Literal["create", "delete"]
    kind: Literal["svi", "loopback"]
    name: str | None = Field(default=None, max_length=64)
    vlan_id: int | None = Field(default=None, ge=1, le=4094)
    ipv4: str | None = Field(default=None, max_length=43)
    mtu: int | None = Field(default=None, ge=64, le=16360)
    enabled: bool | None = None
    dhcp: bool | None = None
    reason: str = Field(default="", max_length=2000)


class RequestRejectIn(BaseModel):
    """Body of ``POST /api/requests/{id}/reject`` — comment required."""

    comment: str = Field(min_length=1, max_length=2000)


class RequestChangesIn(BaseModel):
    """Body of ``POST /api/requests/{id}/request-changes`` — what to revise; required."""

    comment: str = Field(min_length=1, max_length=2000)


class RequestResubmitIn(BaseModel):
    """Body of ``POST /api/requests/{id}/resubmit`` — owner revises and resubmits.

    Both fields optional: omit ``requested_changes`` to resubmit unchanged (e.g.
    after a back-and-forth in comments), or supply edited changes / reason.
    """

    requested_changes: PortChange | None = None
    reason: str | None = Field(default=None, max_length=2000)


class RequestOut(BaseModel):
    """Public view of a change request."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    device_id: str
    port_name: str
    requested_by: str
    # Human-readable requester username, resolved from ``requested_by`` (a user
    # id) by the API layer. None if the user no longer exists. Lets the UI show
    # "who" without the client joining ids→names (non-admins can't list users).
    requested_by_username: str | None = None
    requested_changes: dict[str, object]
    reason: str
    status: ChangeRequestStatus
    reviewer_id: str | None = None
    reviewer_comment: str | None = None
    diff_text: str | None = None
    # The raw ``confirm_token`` is a server-internal secret used by
    # ``change_apply.confirm_request``; it MUST NOT cross the HTTP boundary. We
    # expose only a derived boolean plus the (non-secret) deadline for the UI.
    awaiting_confirm: bool = False
    confirm_deadline_at: float | None = None
    created_at: str
    reviewed_at: str | None = None
    applied_at: str | None = None

    @classmethod
    def from_model(cls, request: ChangeRequest, *, username: str | None = None) -> RequestOut:
        return cls(
            id=request.id,
            device_id=request.device_id,
            port_name=request.port_name,
            requested_by=request.requested_by,
            requested_by_username=username,
            requested_changes=dict(request.requested_changes),
            reason=request.reason,
            status=request.status,
            reviewer_id=request.reviewer_id,
            reviewer_comment=request.reviewer_comment,
            diff_text=request.diff_text,
            awaiting_confirm=request.status == ChangeRequestStatus.AWAITING_CONFIRM,
            confirm_deadline_at=request.confirm_deadline_at,
            created_at=request.created_at.isoformat() if request.created_at else "",
            reviewed_at=request.reviewed_at.isoformat() if request.reviewed_at else None,
            applied_at=request.applied_at.isoformat() if request.applied_at else None,
        )
