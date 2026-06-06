"""Live-validate Pica8 render_vlan_change against the real leaf-01.

Safe: uses an unused high VLAN id, creates → verifies present → deletes →
verifies gone. Pica8 has no confirmed-commit (writes are permanent), so the
delete cleanup is essential.
"""

import asyncio

from sqlalchemy import select

from northbound.db import async_session_factory
from northbound.drivers.factory import driver_for
from northbound.models.device import Device
from northbound.schemas.driver import VlanChange
from northbound.services.credvault import FernetCredVault, deserialize_credentials

TEST_VID = 3997  # unused, cleaned up


async def main() -> None:
    async with async_session_factory() as s:
        dev = (await s.scalars(select(Device).where(Device.name == "leaf-01"))).first()
        if dev is None:
            print("leaf-01 not found")
            return
        creds = deserialize_credentials(dev.encrypted_credentials, FernetCredVault.from_settings())
        driver = driver_for(dev, creds)
        try:
            before = {v.vlan_id for v in await driver.get_vlans()}
            print(
                f"vlans before: {sorted(before)[:8]}... (n={len(before)})  TEST_VID present={TEST_VID in before}"
            )

            # CREATE
            diff = await driver.render_vlan_change(
                VlanChange(action="create", vlan_id=TEST_VID, name="nb-livetest")
            )
            res = await driver.apply_change(diff, confirm_seconds=30)
            print(f"create apply: success={res.success} error={res.error}")
            if res.confirm_token:
                await driver.confirm(res.confirm_token)
            after_create = {v.vlan_id for v in await driver.get_vlans()}
            print(f"  TEST_VID present after create: {TEST_VID in after_create}")

            # DELETE (cleanup)
            ddiff = await driver.render_vlan_change(VlanChange(action="delete", vlan_id=TEST_VID))
            dres = await driver.apply_change(ddiff, confirm_seconds=30)
            print(f"delete apply: success={dres.success} error={dres.error}")
            if dres.confirm_token:
                await driver.confirm(dres.confirm_token)
            after_delete = {v.vlan_id for v in await driver.get_vlans()}
            print(f"  TEST_VID present after delete: {TEST_VID in after_delete}")

            ok = (TEST_VID in after_create) and (TEST_VID not in after_delete) and res.success
            print(f"\nLIVE VALIDATE {'PASS' if ok else 'FAIL'}")
        finally:
            await driver.aclose()


asyncio.run(main())
