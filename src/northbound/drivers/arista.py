"""Arista EOS driver — backed by NAPALM (eos / pyeapi).

We do NOT hand-roll the eAPI JSON-RPC protocol, error handling, or commit-confirm
machinery: NAPALM's ``eos`` driver owns all of it. This module only:
  * adapts our :class:`Driver` ABC onto NAPALM's sync API (every call wrapped in
    ``asyncio.to_thread`` — NAPALM is blocking),
  * maps NAPALM getters → our ``PortState`` / ``Neighbor`` shapes,
  * declares the desired change as EOS config and applies it with NAPALM's
    confirmed-commit (``commit_config(revert_in=…)`` → ``confirm_commit`` /
    ``rollback``),
  * translates NAPALM exceptions → our ``AuthError`` / ``ReachabilityError`` /
    ``DriverError`` taxonomy.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from typing import Any

from napalm import get_network_driver
from napalm.base.exceptions import (  # type: ignore[import-untyped]
    CommandErrorException,
    ConnectionException,
    MergeConfigException,
)

from northbound._lib import lldp
from northbound.drivers.base import (
    AuthError,
    Driver,
    DriverError,
    NotSupported,
    ReachabilityError,
)
from northbound.drivers.config_templates import render_lines
from northbound.drivers.registry import register
from northbound.schemas.driver import (
    ApplyResult,
    AuthMethod,
    ConfigDiff,
    ConnectionParams,
    Credentials,
    DiscoveryResult,
    DriverCapabilities,
    L3Change,
    Neighbor,
    OspfChange,
    PortChange,
    PortState,
    TestResult,
    VlanChange,
    VrfChange,
)

logger = logging.getLogger("northbound.drivers.arista")

_SESSION_KEY = "session_name"


@register
class AristaDriver(Driver):
    """Arista EOS via NAPALM eos (pyeapi/eAPI over HTTPS)."""

    platform_id = "arista"
    display_name = "Arista EOS"
    capabilities = DriverCapabilities(
        writable=True,
        supports_commit_confirm=True,
        native_api_available=True,
        supports_snmp_read=False,
        supports_lldp=True,
        max_concurrency=5,
        auth_methods=[AuthMethod.PASSWORD],
        web_ui_url_template="https://{mgmt_ip}/",
    )

    def __init__(
        self,
        conn: ConnectionParams,
        creds: Credentials,
        *,
        device: Any | None = None,
    ) -> None:
        super().__init__(conn, creds)
        self._device = device  # injected NAPALM device (tests); else built lazily
        self._opened = False

    # ---------- NAPALM lifecycle ----------

    def _build_device(self) -> Any:
        driver = get_network_driver("eos")
        optional_args = {
            "transport": "https",
            "port": self._conn.port or 443,
            # self-signed lab certs: pyeapi verifies only if a context is set;
            # default https transport does not verify, which suits lab use.
        }
        return driver(
            hostname=self._conn.host,
            username=self._creds.username or "",
            password=self._creds.password or "",
            timeout=int(self._conn.timeout_seconds) or 30,
            optional_args=optional_args,
        )

    async def _open(self) -> Any:
        if self._device is None:
            self._device = self._build_device()
        if not self._opened:
            try:
                await asyncio.to_thread(self._device.open)
            except ConnectionException as exc:
                raise ReachabilityError(f"arista: cannot connect: {exc}") from exc
            except Exception as exc:  # auth/SSL/etc. surfaced by pyeapi
                raise _classify(exc) from exc
            self._opened = True
        return self._device

    async def _call(self, fn_name: str, *args: Any, **kwargs: Any) -> Any:
        dev = await self._open()
        fn = getattr(dev, fn_name)
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except (ConnectionException, MergeConfigException, CommandErrorException) as exc:
            raise _classify(exc) from exc
        except Exception as exc:
            raise _classify(exc) from exc

    async def aclose(self) -> None:
        dev, self._device, opened = self._device, None, self._opened
        self._opened = False
        if dev is not None and opened:
            with contextlib.suppress(Exception):  # close must never raise
                await asyncio.to_thread(dev.close)

    # ---------- onboarding / read ----------

    async def test_credentials(self) -> TestResult:
        start = time.monotonic()
        try:
            facts = await self._call("get_facts")
        except AuthError as exc:
            return TestResult(
                ok=False, latency_ms=_ms(start), platform_version=None, error=str(exc)
            )
        except (ReachabilityError, DriverError) as exc:
            return TestResult(
                ok=False, latency_ms=_ms(start), platform_version=None, error=str(exc)
            )
        model = facts.get("model") or ""
        version = facts.get("os_version") or ""
        ver = f"{facts.get('vendor', 'Arista')} {model} {version}".strip()
        return TestResult(ok=True, latency_ms=_ms(start), platform_version=ver or version or None)

    async def reachable(self) -> bool:
        try:
            dev = await self._open()
            alive = await asyncio.to_thread(dev.is_alive)
            return bool(alive.get("is_alive", True))
        except (ReachabilityError, AuthError, DriverError):
            return False

    async def discover(self) -> DiscoveryResult:
        facts = await self._call("get_facts")
        ports = await self.get_ports()
        running = await self.get_running_config()
        return DiscoveryResult(
            hostname=facts.get("hostname", ""),
            ports=tuple(ports),
            running_config=running,
            services={"lldp": self.capabilities.supports_lldp},
        )

    async def get_running_config(self) -> str:
        cfg = await self._call("get_config", retrieve="running")
        running = cfg.get("running", "") if isinstance(cfg, dict) else ""
        return running if isinstance(running, str) else ""

    async def backup_config(self) -> str:
        cfg = await self.get_running_config()
        return cfg if cfg else "! arista: empty running-config\n"

    async def get_ports(self) -> list[PortState]:
        interfaces = await self._call("get_interfaces")
        switchports = await self._switchports()
        return _merge_ports(interfaces, switchports)

    async def _switchports(self) -> dict[str, dict[str, Any]]:
        """Per-port access/trunk VLANs via the pyeapi node's structured
        ``show interfaces switchport`` (NAPALM's get_vlans only lists defined
        VLANs and misses per-port access/native VLAN — verified live)."""
        dev = await self._open()
        try:
            res = await asyncio.to_thread(
                dev.device.run_commands,
                ["show interfaces switchport"],
                encoding="json",
            )
        except Exception:
            # Don't blank per-port VLANs silently — that masquerades as "no VLANs".
            logger.warning(
                "arista switchports query failed; per-port VLANs will be empty",
                exc_info=True,
            )
            return {}
        sw = res[0].get("switchports", {}) if res and isinstance(res[0], dict) else {}
        return sw if isinstance(sw, dict) else {}

    async def get_neighbors(self, port: str | None = None) -> list[Neighbor]:
        try:
            detail = await self._call("get_lldp_neighbors_detail")
        except DriverError:
            return []
        neighbors = _parse_lldp_detail(detail)
        if port is None:
            return neighbors
        return [n for n in neighbors if lldp.local_port_matches(n.system_description, port)]

    # ---------- write (NAPALM confirmed-commit) ----------

    async def render_change(self, port: str, change: PortChange) -> ConfigDiff:
        session = f"nb-{uuid.uuid4().hex[:8]}"
        cmds = _build_change_commands(port, change)
        return ConfigDiff(
            summary=f"Update {port}",
            raw_before=f"interface {port}\n  ! (previous state not captured)\n",
            raw_after="\n".join(cmds) + "\n",
            commands=tuple(cmds),
            metadata={_SESSION_KEY: session},
        )

    def _diff(self, summary: str, cmds: list[str]) -> ConfigDiff:
        return ConfigDiff(
            summary=summary,
            raw_before="! (previous state not captured)\n",
            raw_after="\n".join(cmds) + "\n",
            commands=tuple(cmds),
            metadata={_SESSION_KEY: f"nb-{uuid.uuid4().hex[:8]}"},
        )

    async def render_vlan_change(self, change: VlanChange) -> ConfigDiff:
        """EOS VLAN-database create/delete — rendered from arista/vlan.j2."""
        verb = "Delete" if change.action == "delete" else "Create"
        return self._diff(
            f"{verb} VLAN {change.vlan_id}", render_lines("arista/vlan.j2", **change.model_dump())
        )

    async def render_l3_change(self, change: L3Change) -> ConfigDiff:
        """EOS SVI / loopback create/delete incl. VRF binding — arista/l3.j2.

        SVI interface is ``Vlan<id>`` (EOS-capitalised); loopback uses the given
        name (e.g. ``Loopback1``). The template emits ``vrf forwarding`` before
        ``ip address`` (EOS clears the address on a VRF change)."""
        verb = "Delete" if change.action == "delete" else "Create"
        label = "SVI" if change.kind == "svi" else "loopback"
        return self._diff(
            f"{verb} {label} {change.iface_name}",
            render_lines("arista/l3.j2", **change.model_dump()),
        )

    async def render_ospf_change(self, change: OspfChange) -> ConfigDiff:
        """EOS OSPFv2 change — arista/ospf.j2. Process id defaults to 1; area +
        cost/timers are interface-level, but ``passive-interface`` is under
        ``router ospf`` (the EOS model)."""
        what = "router-id" if change.target == "router-id" else (change.interface or "")
        return self._diff(
            f"OSPF {change.action} {what}", render_lines("arista/ospf.j2", **change.model_dump())
        )

    async def render_vrf_change(self, change: VrfChange) -> ConfigDiff:
        """EOS VRF create/delete (`vrf instance <name>`, 4.22+) — arista/vrf.j2."""
        verb = "Delete" if change.action == "delete" else "Create"
        return self._diff(
            f"{verb} VRF {change.name}", render_lines("arista/vrf.j2", **change.model_dump())
        )

    async def apply_change(self, diff: ConfigDiff, *, confirm_seconds: int = 60) -> ApplyResult:
        session = diff.metadata.get(_SESSION_KEY) or f"nb-{uuid.uuid4().hex[:8]}"
        config = "\n".join(diff.commands)
        # NAPALM owns the eAPI session + confirmed-commit: load the candidate,
        # then commit with a revert timer. If confirm() is not called in time the
        # device rolls back on its own; revert() rolls back immediately.
        try:
            await self._call("load_merge_candidate", config=config)
            await self._call("commit_config", revert_in=max(1, int(confirm_seconds)))
        except (AuthError, ReachabilityError, DriverError) as exc:
            with contextlib.suppress(DriverError):
                await self._call("discard_config")  # clear the loaded candidate
            return ApplyResult(
                success=False, confirm_token=None, confirm_deadline_at=None, error=str(exc)
            )
        return ApplyResult(
            success=True,
            confirm_token=session,
            confirm_deadline_at=time.time() + confirm_seconds,
            error=None,
        )

    async def confirm(self, apply_token: str) -> None:
        # Cancel the revert timer → change becomes permanent.
        await self._call("confirm_commit")

    async def revert(self, apply_token: str) -> None:
        # Roll back the pending (revert_in) commit immediately.
        await self._call("rollback")


# ---------------------------------------------------------------------------
# exception mapping + pure helpers
# ---------------------------------------------------------------------------


def _classify(exc: BaseException) -> DriverError:
    """Map a NAPALM/pyeapi exception to our taxonomy."""
    if isinstance(exc, (AuthError, ReachabilityError, NotSupported, DriverError)):
        return exc
    msg = str(exc)
    low = msg.lower()
    if (
        isinstance(exc, ConnectionException)
        or "unreachable" in low
        or "timed out" in low
        or "connection" in low
    ):
        return ReachabilityError(f"arista: {msg}")
    if "401" in low or "unauthorized" in low or "authentication" in low or "authorization" in low:
        return AuthError(f"arista: {msg}")
    return DriverError(f"arista: {msg}")


def _ms(start: float) -> float:
    return (time.monotonic() - start) * 1000.0


def _merge_ports(interfaces: object, switchports: object) -> list[PortState]:
    """NAPALM get_interfaces + pyeapi ``show interfaces switchport`` → PortState.

    ``switchports`` is ``{name: {"switchportInfo": {"mode", "accessVlanId",
    "trunkingNativeVlanId", "trunkAllowedVlans"}}}``. access → untagged =
    accessVlanId; trunk → untagged = native, tagged = allowed list.
    """
    if not isinstance(interfaces, dict):
        return []
    sw = switchports if isinstance(switchports, dict) else {}

    out: list[PortState] = []
    for name, data in interfaces.items():
        if not isinstance(data, dict):
            continue
        untagged, tagged = _vlans_for(sw.get(name))
        speed = data.get("speed")
        out.append(
            PortState(
                name=name,
                admin_up=bool(data.get("is_enabled", True)),
                link_up=bool(data.get("is_up", False)),
                speed_mbps=int(speed) if isinstance(speed, (int, float)) and speed else None,
                duplex=None,
                mac=(data.get("mac_address") or None),
                mtu=(int(data["mtu"]) if isinstance(data.get("mtu"), (int, float)) else None),
                untagged_vlan=untagged,
                tagged_vlans=tagged,
                description=str(data.get("description") or ""),
                host_model="",
                bmc_ip="",
                notes="",
                services={},
            )
        )
    return out


def _vlans_for(entry: object) -> tuple[int | None, tuple[int, ...]]:
    """Extract (untagged, tagged) from one ``show interfaces switchport`` row."""
    if not isinstance(entry, dict):
        return None, ()
    info = entry.get("switchportInfo")
    if not isinstance(info, dict):
        return None, ()
    mode = str(info.get("mode") or "").lower()
    if "trunk" in mode:
        native = _coerce_vlan(info.get("trunkingNativeVlanId"))
        return native, _parse_allowed(info.get("trunkAllowedVlans"))
    # access (or default) → the access VLAN is the untagged VLAN
    return _coerce_vlan(info.get("accessVlanId")), ()


def _coerce_vlan(v: object) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def _parse_allowed(value: object) -> tuple[int, ...]:
    """Parse an EOS trunk-allowed string ('10,20,30-32') into a VLAN tuple.

    'ALL' / 'NONE' / the full 1-4094 range → () (the UI shouldn't claim to know
    the entire VLAN set)."""
    if not isinstance(value, str):
        return ()
    norm = value.strip().upper()
    if norm in ("ALL", "NONE", "1-4094", ""):
        return ()
    out: list[int] = []
    for tok in value.split(","):
        tok = tok.strip()
        if "-" in tok:
            try:
                lo, hi = (int(x) for x in tok.split("-", 1))
            except ValueError:
                continue
            out.extend(range(lo, hi + 1))
        elif tok.isdigit():
            out.append(int(tok))
    return tuple(out)


def _parse_lldp_detail(detail: object) -> list[Neighbor]:
    """NAPALM get_lldp_neighbors_detail → Neighbor list.

    Shape: ``{local_port: [ {remote_chassis_id, remote_port,
    remote_system_name, remote_system_description}, ... ]}``. The local port is
    encoded into the ``system_description`` ``[<local>] `` prefix (shared
    convention) so ``get_neighbors(port=...)`` can filter.
    """
    if not isinstance(detail, dict):
        return []
    out: list[Neighbor] = []
    for local_port, entries in detail.items():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            chassis = str(e.get("remote_chassis_id") or "").strip()
            rport = str(e.get("remote_port") or e.get("remote_port_description") or "").strip()
            sysname = e.get("remote_system_name")
            sysdesc = str(e.get("remote_system_description") or "").strip()
            out.append(
                Neighbor(
                    chassis_id=lldp.normalize_chassis_id(chassis) if chassis else "",
                    port_id=lldp.normalize_port_id(rport) if rport else "",
                    system_name=sysname if isinstance(sysname, str) and sysname else None,
                    system_description=(lldp.encode_local_port_prefix(str(local_port)) + sysdesc)
                    or None,
                )
            )
    return out


def _build_change_commands(port: str, change: PortChange) -> list[str]:
    """EOS config lines for a PortChange (the change intent NAPALM applies).

    ``tagged_vlans`` ⇒ trunk (native = untagged_vlan, allowed = tagged set,
    replace semantics); else access with the untagged VLAN.
    """
    cmds: list[str] = [f"interface {port}"]
    if change.description is not None:
        cmds.append(f"   description {change.description}")
    if change.tagged_vlans is not None:
        cmds.append("   switchport mode trunk")
        if change.untagged_vlan is not None:
            cmds.append(f"   switchport trunk native vlan {change.untagged_vlan}")
        if change.tagged_vlans:
            allowed = ",".join(str(v) for v in change.tagged_vlans)
            cmds.append(f"   switchport trunk allowed vlan {allowed}")
        else:
            cmds.append("   switchport trunk allowed vlan none")
    elif change.untagged_vlan is not None:
        cmds.append("   switchport mode access")
        cmds.append(f"   switchport access vlan {change.untagged_vlan}")
    return cmds
