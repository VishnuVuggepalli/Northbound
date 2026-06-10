"""Server-Sent Events stream of live state (F157).

A single authenticated stream (`GET /api/events/stream`) pushes live-state
events — device reachability transitions and port-cache invalidations — so the
SPA updates without polling. Auth reuses :func:`get_current_user`, which accepts
the httpOnly session cookie; that matters here because the browser ``EventSource``
API cannot set an ``Authorization`` header, but it does send same-origin cookies.

``sse-starlette`` handles the wire details: periodic keep-alive pings and
cancelling the generator when the client disconnects (which unwinds
``hub.subscribe`` and deregisters the subscriber).

Single-worker scope: an event reaches only clients on the worker that published
it (see ``services.events`` for the Redis swap point).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from northbound.api.deps import get_current_user
from northbound.models.user import User
from northbound.services.events import hub

router = APIRouter(prefix="/api/events", tags=["events"])

# Per-user cap on concurrent SSE streams: each open stream holds a hub queue, a
# task, and a socket, so without a bound one scripted account could exhaust
# file descriptors/memory by holding thousands open. 5 covers a realistic
# many-tabs user. Process-local (same scope as the hub itself).
MAX_STREAMS_PER_USER = 5
_active_streams: Counter[str] = Counter()


async def event_stream(user_id: str | None = None) -> AsyncGenerator[dict[str, str], None]:
    """Yield SSE payloads: an initial ``hello`` then every hub event as JSON.

    Module-level (not nested in the route) so it can be unit-tested directly,
    without driving sse-starlette's wire layer over a test transport.
    The caller (route) increments the per-user stream count BEFORE handing the
    generator to the response — atomic with the cap check, so a parallel burst
    can't slip past it — and this generator releases the slot in ``finally``
    when the client disconnects. (sse-starlette starts iterating immediately,
    so the finally is guaranteed to run.)
    """
    # Own the subscription explicitly and close it in `finally`: a bare
    # `async for ... in hub.subscribe()` does NOT deterministically close the
    # inner generator when this one is closed (client disconnect), so the
    # subscriber would leak until GC. Explicit aclose() runs subscribe()'s
    # cleanup (deregister) the moment the stream ends.
    subscription = hub.subscribe()
    try:
        # Greet immediately so the client knows the stream is established (and
        # the EventSource `onopen` fires) before the first real event.
        yield {"event": "hello", "data": json.dumps({"ok": True})}
        async for event in subscription:
            yield {"event": event.type, "data": json.dumps(event.data)}
    finally:
        if user_id is not None:
            _active_streams[user_id] -= 1
            if _active_streams[user_id] <= 0:
                del _active_streams[user_id]
        await subscription.aclose()


@router.get("/stream")
async def stream(user: Annotated[User, Depends(get_current_user)]) -> EventSourceResponse:
    """Open the live-state SSE stream (authenticated; per-user concurrency cap)."""
    if _active_streams[user.id] >= MAX_STREAMS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many concurrent event streams for this user",
        )
    _active_streams[user.id] += 1
    return EventSourceResponse(event_stream(user.id))
