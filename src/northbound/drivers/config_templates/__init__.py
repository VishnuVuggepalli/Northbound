"""Jinja2 config-rendering templates for driver write paths.

CLI-style platforms (Arista EOS, Cisco) render config as line-per-command
templates here instead of inline f-strings — config syntax lives in ``.j2`` files
that mirror the vendor CLI, reviewable without reading Python.

NETCONF/XML platforms (Pica8) keep using lxml etree building: for XML, lxml is
safer than string templates (auto-escaping + namespace/operation-attr handling).
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_TEMPLATE_DIR = Path(__file__).parent
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=StrictUndefined,  # surface template typos / missing context keys
    keep_trailing_newline=False,
    autoescape=False,  # CLI text, not HTML/XML
)


def render_lines(template: str, /, **context: object) -> list[str]:
    """Render a CLI template to a clean list of command lines (no blanks)."""
    text = _env.get_template(template).render(**context)
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]
