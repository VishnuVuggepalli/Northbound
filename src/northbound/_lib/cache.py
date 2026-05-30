"""In-process caches: LRU (doubly-linked-list + hashmap) and a TTL variant.

``LRUCache`` is an O(1)-get/-set cache with classic DLL + dict eviction.
``TTLCache`` layers per-entry expiry on top: a fresh entry is an LRU hit; an
expired entry reads as a miss and is evicted lazily on access.

These are single-process, single-worker caches (principal-engineering D2/D9).
When Northbound grows past one worker the in-mem dict must become a shared
store (Redis); these classes are the swap point — keep their public surface
(`get` / `set` / `__len__` / `clear`) stable so the migration is an
implementation change, not an API change.

Generic over the value type. Keys are ``str`` (sufficient for our cache keys:
device ids, oids). ``get`` returns a sentinel ``MISS`` on absence/expiry so a
``None`` value is distinguishable from "not present".
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final, Generic, TypeVar

_V = TypeVar("_V")


class CacheMiss:
    """Type of the cache-miss sentinel.

    A distinct class (not ``None``) so a cached ``None`` value is
    distinguishable from absence, and so callers can narrow ``_V | CacheMiss``
    with ``isinstance(x, CacheMiss)`` (which the type checker narrows in both
    branches, unlike an ``is MISS`` identity check on a singleton instance).
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "MISS"


MISS: Final[CacheMiss] = CacheMiss()


@dataclass
class _Node(Generic[_V]):
    """A doubly-linked-list node holding one cache entry.

    ``expires_at`` is a monotonic deadline (seconds) or ``None`` for no expiry.
    Mutable by design — the DLL is an in-place structure; the cache owns it and
    never leaks nodes to callers, so the project's immutability rule (which
    governs value/DTO types) does not apply to this internal plumbing.
    """

    key: str
    value: _V
    expires_at: float | None
    prev: _Node[_V] | None = None
    next: _Node[_V] | None = None


class LRUCache(Generic[_V]):
    """Fixed-capacity LRU cache. O(1) get/set via DLL + dict.

    Most-recently-used sits next to ``_head``; the LRU victim sits next to
    ``_tail``. Sentinel head/tail nodes remove edge-case branching.
    """

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._map: dict[str, _Node[_V]] = {}
        # Sentinels: _head <-> ... <-> _tail. Real nodes live between them.
        self._head: _Node[_V] = _Node("", None, None)  # type: ignore[arg-type]
        self._tail: _Node[_V] = _Node("", None, None)  # type: ignore[arg-type]
        self._head.next = self._tail
        self._tail.prev = self._head

    # ---- DLL plumbing -----------------------------------------------------

    def _unlink(self, node: _Node[_V]) -> None:
        prev, nxt = node.prev, node.next
        assert prev is not None and nxt is not None  # internal nodes only
        prev.next = nxt
        nxt.prev = prev
        node.prev = node.next = None

    def _push_front(self, node: _Node[_V]) -> None:
        first = self._head.next
        assert first is not None
        node.prev = self._head
        node.next = first
        self._head.next = node
        first.prev = node

    def _evict_lru(self) -> None:
        victim = self._tail.prev
        if victim is None or victim is self._head:
            return  # empty
        self._unlink(victim)
        self._map.pop(victim.key, None)

    # ---- public API -------------------------------------------------------

    def get(self, key: str) -> _V | CacheMiss:
        """Return the value and mark it most-recently-used, or ``MISS``."""
        node = self._map.get(key)
        if node is None:
            return MISS
        self._unlink(node)
        self._push_front(node)
        return node.value

    def set(self, key: str, value: _V) -> None:
        """Insert/update ``key``; evict the LRU entry if over capacity."""
        existing = self._map.get(key)
        if existing is not None:
            existing.value = value
            existing.expires_at = None
            self._unlink(existing)
            self._push_front(existing)
            return
        node: _Node[_V] = _Node(key, value, None)
        self._map[key] = node
        self._push_front(node)
        if len(self._map) > self._capacity:
            self._evict_lru()

    def delete(self, key: str) -> None:
        """Remove ``key`` if present (no-op otherwise)."""
        node = self._map.pop(key, None)
        if node is not None:
            self._unlink(node)

    def clear(self) -> None:
        self._map.clear()
        self._head.next = self._tail
        self._tail.prev = self._head

    def __len__(self) -> int:
        return len(self._map)

    def __contains__(self, key: str) -> bool:
        return key in self._map


class TTLCache(LRUCache[_V]):
    """LRU cache where entries expire after ``default_ttl`` seconds.

    Expiry is checked lazily on ``get`` (an expired entry is evicted and reads
    as ``MISS``). ``set`` stamps a deadline; pass ``ttl`` to override the
    default per-entry. Clock source is injectable for deterministic tests.
    """

    def __init__(
        self,
        capacity: int,
        default_ttl: float,
        *,
        clock: object | None = None,
    ) -> None:
        super().__init__(capacity)
        if default_ttl <= 0:
            raise ValueError("default_ttl must be > 0")
        self._default_ttl = default_ttl
        # clock() -> float seconds. time.monotonic by default (immune to wall
        # clock jumps). Typed as a no-arg callable; kept as ``object`` in the
        # signature to avoid a Callable import churn, narrowed here.
        self._clock = clock if callable(clock) else time.monotonic

    def _now(self) -> float:
        return float(self._clock())  # type: ignore[operator]  # narrowed in __init__

    def get(self, key: str) -> _V | CacheMiss:
        node = self._map.get(key)
        if node is None:
            return MISS
        if node.expires_at is not None and self._now() >= node.expires_at:
            # Expired: evict lazily and report a miss.
            self.delete(key)
            return MISS
        self._unlink(node)
        self._push_front(node)
        return node.value

    def set(self, key: str, value: _V, *, ttl: float | None = None) -> None:
        """Insert/update with an expiry ``ttl`` seconds out (default if None)."""
        effective_ttl = self._default_ttl if ttl is None else ttl
        expires_at = self._now() + effective_ttl
        existing = self._map.get(key)
        if existing is not None:
            existing.value = value
            existing.expires_at = expires_at
            self._unlink(existing)
            self._push_front(existing)
            return
        node: _Node[_V] = _Node(key, value, expires_at)
        self._map[key] = node
        self._push_front(node)
        if len(self._map) > self._capacity:
            self._evict_lru()
