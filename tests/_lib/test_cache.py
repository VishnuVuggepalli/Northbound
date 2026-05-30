"""Tests for LRUCache and TTLCache (DLL + hashmap, lazy TTL expiry)."""

from __future__ import annotations

from northbound._lib.cache import MISS, CacheMiss, LRUCache, TTLCache


class _Clock:
    """Deterministic monotonic clock for TTL tests."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# --------------------------------------------------------------------------- #
# LRUCache
# --------------------------------------------------------------------------- #
def test_lru_set_get_hit() -> None:
    cache: LRUCache[int] = LRUCache(capacity=2)
    cache.set("a", 1)
    assert cache.get("a") == 1


def test_lru_miss_returns_sentinel() -> None:
    cache: LRUCache[int] = LRUCache(capacity=2)
    assert isinstance(cache.get("nope"), CacheMiss)
    assert cache.get("nope") is MISS


def test_lru_evicts_least_recently_used() -> None:
    cache: LRUCache[int] = LRUCache(capacity=2)
    cache.set("a", 1)
    cache.set("b", 2)
    # Touch "a" so "b" becomes the LRU victim.
    assert cache.get("a") == 1
    cache.set("c", 3)
    assert isinstance(cache.get("b"), CacheMiss)
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert len(cache) == 2


def test_lru_update_existing_no_growth() -> None:
    cache: LRUCache[int] = LRUCache(capacity=2)
    cache.set("a", 1)
    cache.set("a", 2)
    assert cache.get("a") == 2
    assert len(cache) == 1


def test_lru_delete_and_clear() -> None:
    cache: LRUCache[int] = LRUCache(capacity=3)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.delete("a")
    assert isinstance(cache.get("a"), CacheMiss)
    assert "b" in cache
    cache.clear()
    assert len(cache) == 0
    assert isinstance(cache.get("b"), CacheMiss)


def test_lru_can_cache_none_value() -> None:
    """A cached ``None`` is distinguishable from a miss via the sentinel."""
    cache: LRUCache[int | None] = LRUCache(capacity=2)
    cache.set("a", None)
    assert cache.get("a") is None
    assert not isinstance(cache.get("a"), CacheMiss)


# --------------------------------------------------------------------------- #
# TTLCache
# --------------------------------------------------------------------------- #
def test_ttl_fresh_hit() -> None:
    clock = _Clock()
    cache: TTLCache[int] = TTLCache(capacity=4, default_ttl=30.0, clock=clock)
    cache.set("a", 1)
    clock.advance(10.0)
    assert cache.get("a") == 1


def test_ttl_expiry_is_a_miss() -> None:
    clock = _Clock()
    cache: TTLCache[int] = TTLCache(capacity=4, default_ttl=30.0, clock=clock)
    cache.set("a", 1)
    clock.advance(31.0)
    assert isinstance(cache.get("a"), CacheMiss)
    # Lazily evicted on access.
    assert len(cache) == 0


def test_ttl_per_entry_override() -> None:
    clock = _Clock()
    cache: TTLCache[int] = TTLCache(capacity=4, default_ttl=30.0, clock=clock)
    cache.set("short", 1, ttl=5.0)
    cache.set("long", 2)
    clock.advance(6.0)
    assert isinstance(cache.get("short"), CacheMiss)
    assert cache.get("long") == 2


def test_ttl_still_evicts_lru() -> None:
    clock = _Clock()
    cache: TTLCache[int] = TTLCache(capacity=2, default_ttl=30.0, clock=clock)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")  # make "b" the victim
    cache.set("c", 3)
    assert isinstance(cache.get("b"), CacheMiss)
    assert cache.get("a") == 1
    assert cache.get("c") == 3
