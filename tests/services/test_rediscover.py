"""rediscover_device — non-destructive metadata re-sync + fresh baseline."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.models.config_backup import ConfigBackup
from northbound.models.device import Device
from northbound.models.enums import DeviceRole
from northbound.models.port_metadata import PortMetadata
from northbound.schemas.driver import DiscoveryResult, PortState
from northbound.services.onboarding import rediscover_device


def _port(name: str, desc: str = "") -> PortState:
    return PortState(
        name=name,
        admin_up=True,
        link_up=True,
        speed_mbps=None,
        duplex=None,
        mac=None,
        mtu=None,
        untagged_vlan=None,
        tagged_vlans=(),
        description=desc,
        host_model="",
        bmc_ip="",
        notes="",
        services={},
    )


@pytest.mark.asyncio
async def test_rediscover_adds_new_ports_preserves_edits(db_session: AsyncSession) -> None:
    device = Device(
        name="sw1", environment="lab", platform="mock", role=DeviceRole.LEAF, mgmt_ip="10.0.0.1"
    )
    db_session.add(device)
    await db_session.flush()
    # Existing metadata with a human edit on Port1.
    db_session.add(
        PortMetadata(
            device_id=device.id, port_name="Port1", host_model="Dell", bmc_ip="", notes="hand-typed"
        )
    )
    await db_session.flush()

    # Discovery now reports Port1 (changed desc) + a NEW Port2.
    discovery = DiscoveryResult(
        hostname="sw1",
        ports=(_port("Port1", "VLAN-10 | Supermicro | 10.0.0.9"), _port("Port2")),
        running_config="# fresh baseline\n",
    )
    total, added = await rediscover_device(
        db_session, device=device, discovery=discovery, actor_user_id=None
    )
    assert total == 2
    assert added == 1  # only Port2 is new

    rows = {
        r.port_name: r
        for r in await db_session.scalars(
            select(PortMetadata).where(PortMetadata.device_id == device.id)
        )
    }
    # Port1's human edit is preserved (NOT re-parsed/clobbered).
    assert rows["Port1"].host_model == "Dell"
    assert rows["Port1"].notes == "hand-typed"
    assert "Port2" in rows  # new row added

    # A fresh baseline backup was written.
    backups = (
        await db_session.scalars(select(ConfigBackup).where(ConfigBackup.device_id == device.id))
    ).all()
    assert any(b.config_text == "# fresh baseline\n" for b in backups)
