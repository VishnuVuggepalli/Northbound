"""Device model — a managed switch/router.

``platform`` is the driver ``platform_id`` (free-form string, not an enum, so
new drivers don't require a migration). ``encrypted_credentials`` is the
CredVault ciphertext blob — never plaintext.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from northbound.db import Base
from northbound.models._columns import created_at_col, str_enum, uuid_pk
from northbound.models.enums import DeviceRole, Environment


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    environment: Mapped[Environment] = mapped_column(
        str_enum(Environment, name="environment"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[DeviceRole] = mapped_column(
        str_enum(DeviceRole, name="device_role"), nullable=False
    )
    mgmt_ip: Mapped[str] = mapped_column(String(64), nullable=False)
    ssh_user: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prefer_native_api: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    encrypted_credentials: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[dt.datetime] = created_at_col()
