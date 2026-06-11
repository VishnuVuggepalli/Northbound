"""Site DTO validation: slug stays hostname-shaped; name is a display label.

A site ``name`` is human-facing (spaces/punctuation OK — "Edge DR", "West
Coast"); the hostname-shaped identifier is ``slug``. The only hardening on
``name`` is rejecting control characters / CR-LF (the config/log-injection
vector guarded across the schemas).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from northbound.schemas.site import SiteCreateIn, SiteUpdateIn


@pytest.mark.parametrize("name", ["Edge DR", "West Coast", "West", "lab", "Rack 3 / Row B"])
def test_site_name_accepts_display_labels(name: str) -> None:
    assert SiteCreateIn(slug="edge-dr", name=name).name == name.strip()
    assert SiteUpdateIn(name=name).name == name.strip()


@pytest.mark.parametrize("name", ["x\ny", "x\ry", "x\tz", "bell\x07", "\x00null"])
def test_site_name_rejects_control_chars(name: str) -> None:
    with pytest.raises(ValidationError):
        SiteCreateIn(slug="edge-dr", name=name)
    with pytest.raises(ValidationError):
        SiteUpdateIn(name=name)


def test_site_name_rejects_blank_after_strip() -> None:
    with pytest.raises(ValidationError):
        SiteCreateIn(slug="edge-dr", name="   ")
