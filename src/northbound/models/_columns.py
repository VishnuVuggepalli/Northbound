"""Reusable column helpers shared across models.

UUID primary keys are stored as 36-char strings (SQLite has no native UUID
type, and string UUIDs keep the schema portable to Postgres). ``created_at``
uses a server-side ``CURRENT_TIMESTAMP`` default so the DB stamps the row.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import TypeVar
from uuid import uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

_E = TypeVar("_E", bound=StrEnum)


def str_enum(enum_cls: type[_E], *, name: str) -> SAEnum:
    """SQLAlchemy ``Enum`` that stores the StrEnum *value* (e.g. ``"lab"``).

    SQLAlchemy's ``Enum`` persists member *names* by default; ``values_callable``
    flips it to persist the lowercase string values our schema/UI expect.
    """
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


def new_uuid() -> str:
    """Generate a fresh string UUID for a primary key default."""
    return str(uuid4())


def uuid_pk() -> Mapped[str]:
    """A 36-char string UUID primary key with a Python-side default."""
    return mapped_column(String(36), primary_key=True, default=new_uuid)


def created_at_col() -> Mapped[dt.datetime]:
    """A timezone-aware created timestamp, server-defaulted to now()."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
