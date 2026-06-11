"""Pydantic v2 DTOs for the sites catalog API.

A site is the location/environment a device lives in (formerly the fixed
``lab``/``dc`` enum). Admins manage the catalog at runtime; the ``slug`` is the
stable, URL-safe identifier used in routes and on ``Device.environment``.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

# URL-safe slug: lowercase alnum, internal hyphens, 1-64 chars. Stable/immutable.
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Any C0/C1 control char (incl. CR/LF/TAB). A site ``name`` is a human display
# label (the hostname-shaped identifier is ``slug``), so spaces and printable
# punctuation are legitimate ("Edge DR", "West Coast") — but control characters
# never are, and CR/LF is the same config/log-injection vector guarded elsewhere.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _validate_display_name(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("name must not be blank")
    if _CONTROL_RE.search(v):
        raise ValueError("name must not contain control characters")
    return v


class SiteCreateIn(BaseModel):
    """Body of ``POST /api/sites`` (admin only)."""

    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)

    @field_validator("slug")
    @classmethod
    def _slug_url_safe(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG_RE.match(v):
            raise ValueError(
                "slug must be lowercase alphanumeric with internal hyphens (e.g. 'edge-dr')"
            )
        return v

    @field_validator("name")
    @classmethod
    def _name_no_control_chars(cls, v: str) -> str:
        return _validate_display_name(v)


class SiteUpdateIn(BaseModel):
    """Body of ``PATCH /api/sites/{id}`` — rename only (slug is immutable)."""

    name: str = Field(min_length=1, max_length=128)

    @field_validator("name")
    @classmethod
    def _name_no_control_chars(cls, v: str) -> str:
        return _validate_display_name(v)


class SiteOut(BaseModel):
    """Public view of a site, with a live device count for the picker."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    device_count: int = 0
