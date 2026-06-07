"""Change-requests router — file / approve / apply / reject / confirm.

Requesters may create requests and view their own; admins approve/reject/apply/
confirm. Service-layer exceptions are mapped to HTTP codes here (the single
HTTP boundary): illegal transitions → 409, drift → 409, apply failure → 502,
read-only target → 403 (raised inside the service as an HTTPException already).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.api.deps import get_current_user, require_admin
from northbound.api.limiter import limiter, write_rate_key, write_rate_limit_provider
from northbound.db import get_session
from northbound.models.change_request import ChangeRequest
from northbound.models.change_request_event import ChangeRequestEvent
from northbound.models.device import Device
from northbound.models.enums import ChangeRequestStatus, UserRole
from northbound.models.user import User
from northbound.schemas.driver import L3Change, OspfChange, VlanChange, VrfChange
from northbound.schemas.request import (
    RequestChangesIn,
    RequestCommentIn,
    RequestCreateIn,
    RequestEventOut,
    RequestL3In,
    RequestOspfIn,
    RequestOut,
    RequestRejectIn,
    RequestResubmitIn,
    RequestVlanIn,
    RequestVrfIn,
)
from northbound.services import change_apply, events, requests
from northbound.services.change_apply import ApplyError, ApplyFailed, StateDrift
from northbound.services.requests import AlreadyClaimed, IllegalTransition, RequestError

router = APIRouter(prefix="/api/requests", tags=["requests"])


async def _load_request(session: AsyncSession, request_id: str) -> ChangeRequest:
    req = await requests.get_request(session, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    return req


def _assert_can_read(req: ChangeRequest, user: User) -> None:
    """Object-level authz for read paths.

    A non-admin may only see their own request. We raise 404 (not 403) so the
    response cannot be used to confirm that some other user's request exists.
    Admins may read any request.
    """
    if user.role != UserRole.ADMIN and req.requested_by != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")


async def _load_device(session: AsyncSession, device_id: str) -> Device:
    device = await session.scalar(select(Device).where(Device.id == device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


async def _request_out(session: AsyncSession, req: ChangeRequest) -> RequestOut:
    """Serialize one request, resolving the requester's username for display."""
    names = await requests.usernames_for(session, {req.requested_by})
    return RequestOut.from_model(req, username=names.get(req.requested_by))


@router.post("", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def create_request(
    request: Request,
    body: RequestCreateIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RequestOut:
    """File a change request. 403 if the target device is read-only (fail fast)."""
    device = await _load_device(session, body.device_id)
    req = await requests.create_request(
        session,
        device=device,
        port_name=body.port_name,
        requested_changes=body.requested_changes,
        reason=body.reason,
        user=user,
    )
    return await _request_out(session, req)


@router.post("/vlan", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def create_vlan_request(
    request: Request,
    body: RequestVlanIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RequestOut:
    """File a VLAN-database change request (create/delete a VLAN). 403 if read-only."""
    device = await _load_device(session, body.device_id)
    change = VlanChange(
        action=body.action, vlan_id=body.vlan_id, name=body.name, description=body.description
    )
    req = await requests.create_vlan_request(
        session,
        device=device,
        change=change,
        reason=body.reason,
        user=user,
    )
    return await _request_out(session, req)


@router.post("/ospf", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def create_ospf_request(
    request: Request,
    body: RequestOspfIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RequestOut:
    """File an OSPFv2 config-change request. 403 read-only; 422 if inconsistent."""
    device = await _load_device(session, body.device_id)
    try:
        change = OspfChange(
            action=body.action,
            target=body.target,
            router_id=body.router_id,
            interface=body.interface,
            area=body.area,
            cost=body.cost,
            hello_interval=body.hello_interval,
            dead_interval=body.dead_interval,
            passive=body.passive,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    req = await requests.create_ospf_request(
        session, device=device, change=change, reason=body.reason, user=user
    )
    return await _request_out(session, req)


@router.post("/vrf", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def create_vrf_request(
    request: Request,
    body: RequestVrfIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RequestOut:
    """File a VRF create/delete request. 403 if the device is read-only."""
    device = await _load_device(session, body.device_id)
    change = VrfChange(action=body.action, name=body.name, description=body.description)
    req = await requests.create_vrf_request(
        session, device=device, change=change, reason=body.reason, user=user
    )
    return await _request_out(session, req)


@router.post("/l3", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def create_l3_request(
    request: Request,
    body: RequestL3In,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RequestOut:
    """File a routed-interface change request (SVI / loopback). 403 if read-only.

    422 if the L3 intent is internally inconsistent (e.g. svi without vlan_id,
    create without ipv4) — validated by the L3Change model.
    """
    device = await _load_device(session, body.device_id)
    try:
        change = L3Change(
            action=body.action,
            kind=body.kind,
            name=body.name,
            vlan_id=body.vlan_id,
            ipv4=body.ipv4,
            mtu=body.mtu,
            enabled=body.enabled,
            dhcp=body.dhcp,
            vrf=body.vrf,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    req = await requests.create_l3_request(
        session, device=device, change=change, reason=body.reason, user=user
    )
    return await _request_out(session, req)


@router.get("", response_model=list[RequestOut])
async def list_requests(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mine: bool = False,
    request_status: ChangeRequestStatus | None = None,
) -> list[RequestOut]:
    """List requests.

    Non-admin callers ALWAYS see only their own requests — the client ``?mine``
    flag is ignored for them so it cannot be used to enumerate others' requests.
    Admins see every request and may narrow with ``?mine`` / ``?request_status``.
    """
    is_admin = user.role == UserRole.ADMIN
    # Non-admins are forced to their own id (client `mine` is not trusted);
    # admins may opt into the owner filter via `?mine`.
    mine_user_id = (user.id if mine else None) if is_admin else user.id
    rows = await requests.list_requests(
        session,
        mine_user_id=mine_user_id,
        status=request_status,
    )
    # Resolve all requester usernames in one query (no N+1 over the list).
    names = await requests.usernames_for(session, {r.requested_by for r in rows})
    return [RequestOut.from_model(r, username=names.get(r.requested_by)) for r in rows]


@router.get("/{request_id}", response_model=RequestOut)
async def get_request(
    request_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RequestOut:
    """Request detail, including the rendered diff if available.

    Non-admin callers may only read their own request; a foreign id returns 404
    (object-level authz — see :func:`_assert_can_read`).
    """
    req = await _load_request(session, request_id)
    _assert_can_read(req, user)
    return await _request_out(session, req)


async def _events_out(
    session: AsyncSession, events: list[ChangeRequestEvent]
) -> list[RequestEventOut]:
    """Serialize event-log rows to the timeline DTO, resolving actor usernames."""
    names = await requests.usernames_for(session, {e.actor for e in events})
    out: list[RequestEventOut] = []
    for e in events:
        payload = e.payload or {}
        is_comment = payload.get("kind") == "comment"
        out.append(
            RequestEventOut(
                id=e.id,
                kind="comment" if is_comment else "transition",
                from_status=e.from_status,
                to_status=e.to_status,
                actor=e.actor,
                actor_username=names.get(e.actor),
                body=str(payload.get("body") or "") if is_comment else "",
                created_at=e.created_at.isoformat() if e.created_at else "",
            )
        )
    return out


@router.get("/{request_id}/timeline", response_model=list[RequestEventOut])
async def get_request_timeline(
    request_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[RequestEventOut]:
    """The request's timeline — status transitions + comments, oldest first.

    Object-level authz: a non-admin may only read their own request (404 else)."""
    req = await _load_request(session, request_id)
    _assert_can_read(req, user)
    return await _events_out(session, await requests.list_events(session, request_id))


@router.post(
    "/{request_id}/comments",
    response_model=RequestEventOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def add_request_comment(
    request: Request,
    request_id: str,
    body: RequestCommentIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RequestEventOut:
    """Post a comment to a request (owner or admin — same read authz)."""
    req = await _load_request(session, request_id)
    _assert_can_read(req, user)
    event = await requests.add_comment(session, req, user, body.body)
    out = (await _events_out(session, [event]))[0]
    # Commit BEFORE publishing so a subscriber's SSE-triggered timeline refetch
    # can't race the write (the get_session dependency's later commit is a no-op).
    await session.commit()
    events.hub.publish(events.Event("request.timeline", {"request_id": request_id}))
    return out


@router.post("/{request_id}/approve", response_model=RequestOut)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def approve_request(
    request: Request,
    request_id: str,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RequestOut:
    """Approve (no apply). pending → approved."""
    req = await _load_request(session, request_id)
    try:
        req = await requests.approve_request(session, req, admin)
    except IllegalTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await _request_out(session, req)


@router.post("/{request_id}/reject", response_model=RequestOut)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def reject_request(
    request: Request,
    request_id: str,
    body: RequestRejectIn,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RequestOut:
    """Reject with a required comment. pending → rejected."""
    req = await _load_request(session, request_id)
    try:
        req = await requests.reject_request(session, req, admin, body.comment)
    except IllegalTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _request_out(session, req)


@router.post("/{request_id}/request-changes", response_model=RequestOut)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def request_changes(
    request: Request,
    request_id: str,
    body: RequestChangesIn,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RequestOut:
    """Ask the requester to revise (instead of rejecting). pending → needs_revision."""
    req = await _load_request(session, request_id)
    try:
        req = await requests.request_changes(session, req, admin, body.comment)
    except IllegalTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _request_out(session, req)


@router.post("/{request_id}/resubmit", response_model=RequestOut)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def resubmit_request(
    request: Request,
    request_id: str,
    body: RequestResubmitIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RequestOut:
    """Owner revises and resubmits after a request-changes. needs_revision → pending.

    Only the request's owner may resubmit; a foreign id returns 404 (no existence
    leak), mirroring the read-path authz.
    """
    req = await _load_request(session, request_id)
    if req.requested_by != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    device = await _load_device(session, req.device_id)
    try:
        req = await requests.resubmit_request(
            session,
            req,
            user,
            device=device,
            requested_changes=body.requested_changes,
            reason=body.reason,
        )
    except IllegalTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    # A read-only device raises HTTPException(403) directly via assert_writable.
    return await _request_out(session, req)


@router.post("/{request_id}/apply", response_model=RequestOut)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def apply_request(
    request: Request,
    request_id: str,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RequestOut:
    """Apply an approved (or pending, approve+apply shortcut) request via the driver."""
    req = await _load_request(session, request_id)
    device = await _load_device(session, req.device_id)
    try:
        req = await change_apply.apply_request(session, req, device, admin)
    except StateDrift as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "STATE_DRIFT", "message": str(exc)},
        ) from exc
    except ApplyFailed as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except AlreadyClaimed as exc:
        # A concurrent apply already claimed this request → 409, no device push.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ALREADY_CLAIMED", "message": str(exc)},
        ) from exc
    except IllegalTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ApplyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await _request_out(session, req)


@router.post("/{request_id}/confirm", response_model=RequestOut)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def confirm_request(
    request: Request,
    request_id: str,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RequestOut:
    """Confirm a commit-confirm apply within its window. awaiting_confirm → applied."""
    req = await _load_request(session, request_id)
    device = await _load_device(session, req.device_id)
    try:
        req = await change_apply.confirm_request(session, req, device, admin)
    except ApplyFailed as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except IllegalTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ApplyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await _request_out(session, req)
