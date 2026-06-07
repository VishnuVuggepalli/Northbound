"""Sites catalog API — ``/api/sites``.

The sites catalog replaces the old fixed lab/dc environment enum. Any
authenticated user can list sites (the onboarding picker needs them); only
admins create, rename, or delete. A site with attached devices cannot be
deleted (referential safety, since ``Device.environment`` is a soft slug
reference rather than a hard FK).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.api.deps import get_current_user, require_admin
from northbound.db import get_session
from northbound.models.site import Site
from northbound.models.user import User
from northbound.schemas.site import SiteCreateIn, SiteOut, SiteUpdateIn
from northbound.services.sites import device_count_by_slug

router = APIRouter(prefix="/api/sites", tags=["sites"])


def _site_out(site: Site, counts: dict[str, int]) -> SiteOut:
    return SiteOut(
        id=site.id,
        slug=site.slug,
        name=site.name,
        device_count=counts.get(site.slug, 0),
    )


@router.get("", response_model=list[SiteOut])
async def list_sites(
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SiteOut]:
    """List every site in the catalog, with live device counts."""
    counts = await device_count_by_slug(session)
    rows = await session.scalars(select(Site).order_by(Site.name))
    return [_site_out(s, counts) for s in rows.all()]


@router.post("", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
async def create_site(
    body: SiteCreateIn,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteOut:
    """Create a new site (admin only). Slug must be unique."""
    site = Site(slug=body.slug, name=body.name)
    session.add(site)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Site slug '{body.slug}' already exists",
        ) from exc
    return _site_out(site, {})


async def _get_site_or_404(session: AsyncSession, site_id: str) -> Site:
    site = await session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    return site


@router.patch("/{site_id}", response_model=SiteOut)
async def rename_site(
    site_id: str,
    body: SiteUpdateIn,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteOut:
    """Rename a site (admin only). The slug is immutable to keep URLs stable."""
    site = await _get_site_or_404(session, site_id)
    site.name = body.name
    await session.flush()
    counts = await device_count_by_slug(session)
    return _site_out(site, counts)


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(
    site_id: str,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Delete a site (admin only). Blocked if any device is still assigned."""
    site = await _get_site_or_404(session, site_id)
    counts = await device_count_by_slug(session)
    attached = counts.get(site.slug, 0)
    if attached:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Site '{site.slug}' has {attached} device(s); reassign or remove them first",
        )
    await session.delete(site)
