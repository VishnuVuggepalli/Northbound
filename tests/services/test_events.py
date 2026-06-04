"""EventHub pub/sub + the two live-state producers (reachability, port_state)."""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from northbound.services import port_state, reachability
from northbound.services.events import _QUEUE_MAXSIZE, Event, EventHub, hub

pytestmark = pytest.mark.asyncio


async def _register(hub_: EventHub):
    """Subscribe and wait until the NEW subscriber is registered.

    Returns ``(async_generator, task)`` where ``task`` is a started ``__anext__``
    so the caller can await the next event. Waits for the subscriber *count to
    rise* (not merely be non-zero), so it is correct for the 2nd+ subscriber.
    """
    before = hub_.subscriber_count
    agen = hub_.subscribe()
    task = asyncio.create_task(agen.__anext__())
    for _ in range(50):
        if hub_.subscriber_count > before:
            break
        await asyncio.sleep(0.005)
    return agen, task


async def test_publish_reaches_subscriber() -> None:
    h = EventHub()
    agen, task = await _register(h)
    h.publish(Event("device.ports", {"device_id": "d1"}))
    ev = await asyncio.wait_for(task, 1.0)
    assert ev.type == "device.ports"
    assert ev.data == {"device_id": "d1"}
    await agen.aclose()
    assert h.subscriber_count == 0


async def test_fanout_to_multiple_subscribers() -> None:
    h = EventHub()
    a_gen, a_task = await _register(h)
    b_gen, b_task = await _register(h)
    assert h.subscriber_count == 2
    h.publish(Event("x", {"n": 1}))
    a, b = await asyncio.wait_for(asyncio.gather(a_task, b_task), 1.0)
    assert a.data == b.data == {"n": 1}
    await a_gen.aclose()
    await b_gen.aclose()


async def test_publish_with_no_subscribers_is_a_noop() -> None:
    h = EventHub()
    h.publish(Event("x", {}))  # must not raise
    assert h.subscriber_count == 0


async def test_slow_consumer_drops_oldest_not_newest() -> None:
    """Over-full queue evicts the OLDEST event; the newest snapshot survives."""
    h = EventHub()
    agen, first = await _register(h)
    # Flood past capacity without the consumer reading (the pending __anext__
    # task holds one, so push capacity+slack more).
    total = _QUEUE_MAXSIZE + 10
    for i in range(total):
        h.publish(Event("tick", {"i": i}))
    # Drain everything currently buffered.
    seen = [await asyncio.wait_for(first, 1.0)]
    # Pull the rest non-blockingly via fresh __anext__ until it would block.
    while True:
        nxt = asyncio.create_task(agen.__anext__())
        try:
            seen.append(await asyncio.wait_for(nxt, 0.1))
        except TimeoutError:
            nxt.cancel()
            break
    indices = [e.data["i"] for e in seen]
    # The most recent event must be present; the very first must have been dropped.
    assert total - 1 in indices
    assert 0 not in indices
    await agen.aclose()


async def test_reachability_record_reports_transitions() -> None:
    reachability._MAP.clear()
    now = dt.datetime.now(tz=dt.UTC)
    assert reachability.record("d1", reachable=True, checked_at=now) is True  # first obs
    assert reachability.record("d1", reachable=True, checked_at=now) is False  # no change
    assert reachability.record("d1", reachable=False, checked_at=now) is True  # flipped
    reachability._MAP.clear()


async def test_port_state_invalidate_publishes_device_ports() -> None:
    agen, task = await _register(hub)
    port_state.invalidate("dev-42")
    ev = await asyncio.wait_for(task, 1.0)
    assert ev.type == "device.ports"
    assert ev.data == {"device_id": "dev-42"}
    await agen.aclose()
