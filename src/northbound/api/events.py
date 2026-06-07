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
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from northbound.api.deps import get_current_user
from northbound.models.user import User
from northbound.services.events import hub

router = APIRouter(prefix="/api/events", tags=["events"])


async def event_stream() -> AsyncGenerator[dict[str, str], None]:
    """Yield SSE payloads: an initial ``hello`` then every hub event as JSON.

    Module-level (not nested in the route) so it can be unit-tested directly,
    without driving sse-starlette's wire layer over a test transport.
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
        await subscription.aclose()


@router.get("/stream")
async def stream(_user: Annotated[User, Depends(get_current_user)]) -> EventSourceResponse:
    """Open the live-state SSE stream (authenticated)."""
    return EventSourceResponse(event_stream())
