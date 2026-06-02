"""Sites catalog service — seed + lookup helpers.

The sites catalog replaces the old fixed ``lab``/``dc`` environment enum. The
two original environments are seeded as default sites so existing routes,
devices, and bookmarks keep working; admins add more at runtime via the API.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.models.device import Device
from northbound.models.site import Site

# The two original environments, preserved as default sites (slug -> name).
DEFAULT_SITES: tuple[tuple[str, str], ...] = (
    ("lab", "Lab"),
    ("dc", "Datacenter"),
)


async def ensure_default_sites(session: AsyncSession) -> None:
    """Idempotently seed the default Lab/DC sites if the catalog is missing them.

    Safe to call repeatedly (startup + tests): only inserts slugs not present.
    The caller owns the transaction/commit.
    """
    existing = set((await session.scalars(select(Site.slug))).all())
    for slug, name in DEFAULT_SITES:
        if slug not in existing:
            session.add(Site(slug=slug, name=name))


async def site_exists(session: AsyncSession, slug: str) -> bool:
    """True if a site with ``slug`` is in the catalog."""
    return (await session.scalar(select(Site.id).where(Site.slug == slug))) is not None


async def device_count_by_slug(session: AsyncSession) -> dict[str, int]:
    """Map of site slug -> number of devices currently in that site."""
    rows = await session.execute(
        select(Device.environment, func.count(Device.id)).group_by(Device.environment)
    )
    return {slug: count for slug, count in rows.all()}
