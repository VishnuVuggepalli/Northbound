"""Runtime settings — admin-tunable knobs with an in-memory read cache.

The durable source of truth is the ``runtime_settings`` table; this module keeps
a process-local cache so hot read paths (e.g. the per-request rate-limit
provider) never hit the DB. ``load_cache`` seeds it at startup; ``set_value``
writes through both the DB and the cache.

Currently the only knob is the write-endpoint rate limit, expressed as a
``limits`` string (e.g. ``"30/minute"``). Validation reuses the same parser
slowapi uses, so an admin can only persist a value slowapi can enforce.
"""

from __future__ import annotations

import datetime as dt
import os

from limits import parse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.models.runtime_setting import RuntimeSetting

WRITE_RATE_LIMIT_KEY = "write_rate_limit"

# Process-local cache: key -> value. Seeded by load_cache(), updated by set_value().
_cache: dict[str, str] = {}


def default_write_rate_limit() -> str:
    """Env-seeded default used until/unless an admin overrides it in the DB."""
    return os.environ.get("NB_WRITE_RATE_LIMIT", "30/minute")


def current_write_rate_limit() -> str:
    """The active write rate-limit string (cache → env default). Never raises."""
    return _cache.get(WRITE_RATE_LIMIT_KEY) or default_write_rate_limit()


def validate_rate_limit(value: str) -> None:
    """Raise ``ValueError`` if ``value`` is not a slowapi/``limits`` rate string."""
    try:
        parsed = parse(value)
    except Exception as exc:  # limits raises a bare ValueError-ish on bad input
        raise ValueError(f"invalid rate limit {value!r}: {exc}") from exc
    if parsed is None:
        raise ValueError(f"invalid rate limit {value!r}")


async def load_cache(session: AsyncSession) -> None:
    """Populate the in-memory cache from the table (call once at startup)."""
    _cache.clear()
    for row in (await session.scalars(select(RuntimeSetting))).all():
        _cache[row.key] = row.value


async def set_value(session: AsyncSession, key: str, value: str, *, updated_by: str) -> None:
    """Upsert a setting (DB + cache). Caller validates ``value`` first."""
    row = await session.get(RuntimeSetting, key)
    now = dt.datetime.now(tz=dt.UTC)
    if row is None:
        session.add(RuntimeSetting(key=key, value=value, updated_by=updated_by, updated_at=now))
    else:
        row.value = value
        row.updated_by = updated_by
        row.updated_at = now
    await session.flush()
    _cache[key] = value
