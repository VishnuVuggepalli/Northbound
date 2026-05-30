"""Pydantic v2 DTOs for the change-requests API surface."""

from __future__ import annotations

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


class RequestRejectIn(BaseModel):
    """Body of ``POST /api/requests/{id}/reject`` — comment required."""

    comment: str = Field(min_length=1, max_length=2000)


class RequestOut(BaseModel):
    """Public view of a change request."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    device_id: str
    port_name: str
    requested_by: str
    requested_changes: dict[str, object]
    reason: str
    status: ChangeRequestStatus
    reviewer_id: str | None = None
    reviewer_comment: str | None = None
    diff_text: str | None = None
    confirm_token: str | None = None
    confirm_deadline_at: float | None = None
    created_at: str
    reviewed_at: str | None = None
    applied_at: str | None = None

    @classmethod
    def from_model(cls, request: ChangeRequest) -> RequestOut:
        return cls(
            id=request.id,
            device_id=request.device_id,
            port_name=request.port_name,
            requested_by=request.requested_by,
            requested_changes=dict(request.requested_changes),
            reason=request.reason,
            status=request.status,
            reviewer_id=request.reviewer_id,
            reviewer_comment=request.reviewer_comment,
            diff_text=request.diff_text,
            confirm_token=request.confirm_token,
            confirm_deadline_at=request.confirm_deadline_at,
            created_at=request.created_at.isoformat() if request.created_at else "",
            reviewed_at=request.reviewed_at.isoformat() if request.reviewed_at else None,
            applied_at=request.applied_at.isoformat() if request.applied_at else None,
        )
