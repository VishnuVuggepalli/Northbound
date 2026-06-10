"""User model — humans who log in (admins and requesters)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from northbound.db import Base
from northbound.models._columns import created_at_col, str_enum, uuid_pk
from northbound.models.enums import UserRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = uuid_pk()
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole, name="user_role"), nullable=False)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Bumped on every password change/reset. JWTs carry it as the ``ver`` claim
    # and are rejected on mismatch — the only way to revoke stateless tokens.
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[dt.datetime] = created_at_col()
