"""In-process event hub for server-sent live state (F157).

A tiny async pub/sub: producers call :meth:`EventHub.publish`; the SSE endpoint
:func:`subscribe`\\ s and forwards each event to a connected browser via
``EventSource``. Two producers feed it today — device reachability transitions
(the reachability poll) and port-cache invalidation after a write — so the UI
updates without polling.

Single-worker scope (principal-engineering D9), exactly like ``reachability._MAP``
and ``port_state._cache``: this hub is process-local, so an event published in
one worker reaches only the SSE clients connected to that same worker. The
multi-worker swap point is a shared broker (Redis pub/sub) — ``publish`` writes
to a channel and ``subscribe`` reads from it, with these signatures unchanged.

Subscriber queues are **bounded**. A client too slow to keep up drops its
OLDEST buffered events (this is live state — the newest snapshot supersedes a
stale one) rather than growing memory without bound or blocking the publisher.
This module is a leaf: it imports only the stdlib, so any service can publish to
it without an import cycle.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

# Per-subscriber buffer depth. Live-state events are small and supersede each
# other, so a modest buffer absorbs bursts; beyond it, oldest events are dropped.
_QUEUE_MAXSIZE = 100


@dataclass(frozen=True)
class Event:
    """A live-state event. ``type`` is the SSE event name; ``data`` is JSON-able."""

    type: str
    data: dict[str, Any]


class EventHub:
    """Process-local fan-out pub/sub. Not safe across workers (see module docs)."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()

    def publish(self, event: Event) -> None:
        """Fan ``event`` out to every subscriber. Never blocks; drops oldest on a
        full (slow-consumer) queue. Safe to call from sync code."""
        for queue in self._subscribers:
            _offer(queue, event)

    async def subscribe(self) -> AsyncGenerator[Event, None]:
        """Yield events until the consumer stops iterating (e.g. client disconnect).

        Registers a bounded queue on entry and always deregisters it on exit, so
        a disconnected SSE client leaves no dangling subscriber.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        """Number of currently-connected subscribers (for tests / diagnostics)."""
        return len(self._subscribers)


def _offer(queue: asyncio.Queue[Event], event: Event) -> None:
    """Enqueue ``event``, evicting the oldest if the queue is full."""
    with contextlib.suppress(asyncio.QueueFull):
        queue.put_nowait(event)
        return
    with contextlib.suppress(asyncio.QueueEmpty):
        queue.get_nowait()  # drop oldest
    with contextlib.suppress(asyncio.QueueFull):  # racing consumer may refill it
        queue.put_nowait(event)


# Process-wide hub. SWAP POINT for Redis pub/sub at multi-worker scale.
hub = EventHub()
