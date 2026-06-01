"""Cisco driver — backed by NAPALM (nxos for NX-API, ios for SSH).

No hand-rolled NX-API JSON-RPC or SSH command plumbing: NAPALM's ``nxos`` /
``ios`` drivers own transport, error handling, and confirmed-commit
(``commit_config(revert_in=…)`` → ``confirm_commit`` / ``rollback``). This module
adapts to the :class:`Driver` ABC (async via ``asyncio.to_thread``), reads
per-port VLANs from ``.cli()`` output via the maintained ntc-templates TextFSM
templates (NAPALM getters don't expose switchport VLANs), declares changes as
config, and maps NAPALM exceptions → our taxonomy.

``prefer_native_api=True`` → NX-OS via NX-API (``nxos``); ``False`` → IOS/IOS-XE
via SSH (``ios``).
"""

from __future__ import annotations

import asyncio
import contextlib
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
from northbound.drivers.registry import register
from northbound.schemas.driver import (
    ApplyResult,
    AuthMethod,
    ConfigDiff,
    ConnectionParams,
    Credentials,
    DiscoveryResult,
    DriverCapabilities,
    Neighbor,
    PortChange,
    PortState,
    TestResult,
)

_CHECKPOINT_KEY = "checkpoint_name"


@register
class CiscoDriver(Driver):
    """Cisco NX-OS (NX-API) / IOS-XE (SSH) via NAPALM."""

    platform_id = "cisco"
    display_name = "Cisco IOS / NX-OS"
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
        self._use_native = conn.prefer_native_api
        self._device = device
        self._opened = False

    # ---------- NAPALM lifecycle ----------

    def _napalm_name(self) -> str:
        return "nxos" if self._use_native else "ios"

    def _build_device(self) -> Any:
        driver = get_network_driver(self._napalm_name())
        optional_args: dict[str, Any] = {"port": self._conn.port} if self._conn.port else {}
        if not self._use_native and self._creds.enable_secret:
            optional_args["secret"] = self._creds.enable_secret
        return driver(
            hostname=self._conn.host,
            username=self._creds.username or "",
            password=self._creds.password or "",
            timeout=int(self._conn.timeout_seconds) or 60,
            optional_args=optional_args,
        )

    async def _open(self) -> Any:
        if self._device is None:
            self._device = self._build_device()
        if not self._opened:
            try:
                await asyncio.to_thread(self._device.open)
            except ConnectionException as exc:
                raise ReachabilityError(f"cisco: cannot connect: {exc}") from exc
            except Exception as exc:
                raise _classify(exc) from exc
            self._opened = True
        return self._device

    async def _call(self, fn_name: str, *args: Any, **kwargs: Any) -> Any:
        dev = await self._open()
        try:
            return await asyncio.to_thread(getattr(dev, fn_name), *args, **kwargs)
        except (ConnectionException, MergeConfigException, CommandErrorException) as exc:
            raise _classify(exc) from exc
        except Exception as exc:
            raise _classify(exc) from exc

    async def aclose(self) -> None:
        dev, self._device, opened = self._device, None, self._opened
        self._opened = False
        if dev is not None and opened:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(dev.close)

    # ---------- onboarding / read ----------

    async def test_credentials(self) -> TestResult:
        start = time.monotonic()
        try:
            facts = await self._call("get_facts")
        except (AuthError, ReachabilityError, DriverError) as exc:
            return TestResult(
                ok=False, latency_ms=_ms(start), platform_version=None, error=str(exc)
            )
        ver = " ".join(str(x) for x in (facts.get("model"), facts.get("os_version")) if x).strip()
        return TestResult(ok=True, latency_ms=_ms(start), platform_version=ver or None)

    async def reachable(self) -> bool:
        try:
            dev = await self._open()
            return bool((await asyncio.to_thread(dev.is_alive)).get("is_alive", True))
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
        return cfg if cfg else "! cisco: empty running-config\n"

    async def get_ports(self) -> list[PortState]:
        interfaces = await self._call("get_interfaces")
        vlans = await self._switchport_vlans()
        return _merge_ports(interfaces, vlans)

    async def _switchport_vlans(self) -> dict[str, tuple[int | None, tuple[int, ...]]]:
        """Per-port VLANs via NAPALM ``.cli()`` + ntc-templates (NAPALM getters
        don't expose switchport VLANs). NX-OS: ``show interface switchport``;
        IOS: ``show interfaces status``."""
        cmd, platform = (
            ("show interface switchport", "cisco_nxos")
            if self._use_native
            else ("show interfaces status", "cisco_ios")
        )
        try:
            out = await self._call("cli", [cmd])
        except DriverError:
            return {}
        text = out.get(cmd, "") if isinstance(out, dict) else ""
        return _parse_switchport_text(platform, cmd, str(text))

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
        token = f"nb-{uuid.uuid4().hex[:8]}"
        cmds = _build_change_commands(port, change)
        return ConfigDiff(
            summary=f"Update {port}",
            raw_before=f"interface {port}\n  ! (previous state not captured)\n",
            raw_after="\n".join(cmds) + "\n",
            commands=tuple(cmds),
            metadata={_CHECKPOINT_KEY: token},
        )

    async def apply_change(self, diff: ConfigDiff, *, confirm_seconds: int = 60) -> ApplyResult:
        token = diff.metadata.get(_CHECKPOINT_KEY) or f"nb-{uuid.uuid4().hex[:8]}"
        config = "\n".join(diff.commands)
        try:
            await self._call("load_merge_candidate", config=config)
            await self._call("commit_config", revert_in=max(1, int(confirm_seconds)))
        except (AuthError, ReachabilityError, DriverError) as exc:
            with contextlib.suppress(DriverError):
                await self._call("discard_config")
            return ApplyResult(
                success=False, confirm_token=None, confirm_deadline_at=None, error=str(exc)
            )
        return ApplyResult(
            success=True,
            confirm_token=token,
            confirm_deadline_at=time.time() + confirm_seconds,
            error=None,
        )

    async def confirm(self, apply_token: str) -> None:
        await self._call("confirm_commit")

    async def revert(self, apply_token: str) -> None:
        await self._call("rollback")


# ---------------------------------------------------------------------------
# exception mapping + pure helpers
# ---------------------------------------------------------------------------


def _classify(exc: BaseException) -> DriverError:
    if isinstance(exc, (AuthError, ReachabilityError, NotSupported, DriverError)):
        return exc
    low = str(exc).lower()
    if isinstance(exc, ConnectionException) or any(
        s in low for s in ("unreachable", "timed out", "timeout", "refused", "connection")
    ):
        return ReachabilityError(f"cisco: {exc}")
    if any(
        s in low for s in ("authentication", "authorization", "unauthorized", "401", "permission")
    ):
        return AuthError(f"cisco: {exc}")
    return DriverError(f"cisco: {exc}")


def _ms(start: float) -> float:
    return (time.monotonic() - start) * 1000.0


def _parse_switchport_text(
    platform: str, command: str, text: str
) -> dict[str, tuple[int | None, tuple[int, ...]]]:
    """ntc-templates parse of switchport/status text → {iface: (untagged, tagged)}."""
    if not text.strip():
        return {}
    try:
        from ntc_templates.parse import parse_output

        rows = parse_output(platform=platform, command=command, data=text)
    except Exception:
        return {}
    out: dict[str, tuple[int | None, tuple[int, ...]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("interface") or row.get("port") or "").strip()
        if not name:
            continue
        mode = str(row.get("mode") or "").lower()
        if "trunk" in mode:
            untagged = _coerce_int(row.get("native_vlan"))
            tagged = _parse_vlan_list(
                row.get("trunking_vlans")
                or row.get("trunk_vlans")
                or row.get("trunk_vlans_allowed")
            )
            out[name] = (untagged, tagged)
        else:
            untagged = _coerce_int(row.get("access_vlan") or row.get("vlan_id") or row.get("vlan"))
            out[name] = (untagged, ())
    return out


def _merge_ports(
    interfaces: object, vlans: dict[str, tuple[int | None, tuple[int, ...]]]
) -> list[PortState]:
    if not isinstance(interfaces, dict):
        return []
    out: list[PortState] = []
    for name, data in interfaces.items():
        if not isinstance(data, dict):
            continue
        untagged, tagged = vlans.get(name, (None, ()))
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


def _parse_lldp_detail(detail: object) -> list[Neighbor]:
    """NAPALM get_lldp_neighbors_detail → Neighbor list (local port encoded in
    the system_description ``[<local>] `` prefix)."""
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


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _parse_vlan_list(value: object) -> tuple[int, ...]:
    """Parse an NX-OS/IOS trunk VLAN list ('10,20,30-32' or a list) → tuple.
    'ALL'/'NONE'/full range → ()."""
    if isinstance(value, list):
        value = ",".join(str(v) for v in value)
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


def _build_change_commands(port: str, change: PortChange) -> list[str]:
    """Cisco config lines for a PortChange (intent NAPALM applies).

    A bare ``switchport`` precedes mode/VLAN: NX-OS ports default to routed and
    reject ``switchport mode ...`` until made L2 (verified live on NX-OS 7.3);
    idempotent on already-L2 ports. ``tagged_vlans`` ⇒ trunk (replace allowed
    set); else access.
    """
    cmds: list[str] = [f"interface {port}"]
    if change.description is not None:
        cmds.append(f"  description {change.description}")
    if change.tagged_vlans is not None or change.untagged_vlan is not None:
        cmds.append("  switchport")
    if change.tagged_vlans is not None:
        cmds.append("  switchport mode trunk")
        if change.untagged_vlan is not None:
            cmds.append(f"  switchport trunk native vlan {change.untagged_vlan}")
        if change.tagged_vlans:
            allowed = ",".join(str(v) for v in change.tagged_vlans)
            cmds.append(f"  switchport trunk allowed vlan {allowed}")
        else:
            cmds.append("  switchport trunk allowed vlan none")
    elif change.untagged_vlan is not None:
        cmds.append("  switchport mode access")
        cmds.append(f"  switchport access vlan {change.untagged_vlan}")
    return cmds
