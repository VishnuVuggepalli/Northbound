"""Arista EOS driver — eAPI (JSON-RPC over HTTPS).

Write path uses ``configure session <name>`` + ``commit timer 0:<seconds>``
which is Arista's commit-confirmed equivalent. The session name lives in
``ConfigDiff.metadata['session_name']`` and is what ``confirm`` / ``revert``
operate on.

Wire format (eAPI):
    POST https://<host>/command-api
    Body: {"jsonrpc": "2.0", "method": "runCmds",
           "params": {"version": 1, "cmds": [...], "format": "json"|"text"},
           "id": "nb-..."}
    Response: {"jsonrpc": "2.0", "result": [...]} OR {"error": {...}}

Only the JSON contract is touched here — every byte of HTTP goes through
``HttpxClient`` (semaphore, TLS verify, timeout). Driver never imports
``httpx`` directly.
"""

from __future__ import annotations

import time
import uuid
from typing import cast

from northbound._lib import lldp
from northbound._lib.transport.httpx_client import HttpxClient, HttpxParams
from northbound.drivers.base import (
    AuthError,
    Driver,
    DriverError,
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

# eAPI error codes that map to AuthError. eAPI returns HTTP 401 for bad
# basic-auth before JSON-RPC ever runs, but some configurations return
# 200 + JSON error — handle both.
_AUTH_ERROR_CODES = {1000, 1001, 1002}  # documented as auth / permission

# ConfigDiff metadata keys (kept here to avoid magic strings).
_SESSION_KEY = "session_name"


@register
class AristaDriver(Driver):
    """Arista EOS via eAPI."""

    platform_id = "arista"
    display_name = "Arista EOS"
    capabilities = DriverCapabilities(
        writable=True,
        supports_commit_confirm=True,
        native_api_available=True,
        supports_snmp_read=True,
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
        http: HttpxClient | None = None,
    ) -> None:
        super().__init__(conn, creds)
        self._http: HttpxClient | None = http if http is not None else self._build_http()

    async def aclose(self) -> None:
        """Close the eAPI http transport. Idempotent."""
        http = self._http
        if http is not None:
            self._http = None
            await http.aclose()

    # ---------- transport plumbing ----------

    def _build_http(self) -> HttpxClient:
        scheme = "https"
        port = self._conn.port or 443
        base_url = f"{scheme}://{self._conn.host}:{port}"
        return HttpxClient(
            HttpxParams(
                base_url=base_url,
                timeout_seconds=self._conn.timeout_seconds,
                max_concurrency=self.capabilities.max_concurrency,
                verify_tls=False,  # lab default; production wires this off conn
            )
        )

    def _auth_header(self) -> dict[str, str]:
        username = self._creds.username or ""
        password = self._creds.password or ""
        return HttpxClient.basic_auth_header(username, password)

    def _enable_cmd(self) -> object:
        """eAPI ``enable`` command, object form if an enable secret is set.

        Bare ``"enable"`` fails on a device with an enable secret; eAPI wants
        ``{"cmd": "enable", "input": "<secret>"}``. The secret is never logged.
        """
        secret = self._creds.enable_secret
        if secret:
            return {"cmd": "enable", "input": secret}
        return "enable"

    async def _run_cmds(
        self,
        cmds: list[object],
        *,
        fmt: str = "json",
        request_id: str | None = None,
    ) -> list[object]:
        """Execute one or more EOS commands. Returns ``result`` list verbatim.

        Raises:
            AuthError: HTTP 401 or eAPI auth error code.
            ReachabilityError: connection refused / DNS / timeout.
            DriverError: any other eAPI failure.
        """
        if self._http is None:
            raise ReachabilityError("arista: eAPI transport is closed")
        rid = request_id or f"nb-{uuid.uuid4().hex[:8]}"
        body = {
            "jsonrpc": "2.0",
            "method": "runCmds",
            "params": {"version": 1, "cmds": cmds, "format": fmt},
            "id": rid,
        }
        try:
            response = await self._http.post(
                "/command-api",
                headers=self._auth_header(),
                json=body,
            )
        except Exception as exc:  # transport-level failures
            raise ReachabilityError(f"arista eAPI transport error: {exc}") from exc

        if response.status_code == 401:
            raise AuthError("arista eAPI returned 401")
        if response.status_code >= 400:
            raise DriverError(f"arista eAPI HTTP {response.status_code}: {response.text}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise DriverError(f"arista eAPI: non-dict response: {payload!r}")
        if "error" in payload:
            err = payload["error"]
            code = err.get("code") if isinstance(err, dict) else None
            msg = err.get("message") if isinstance(err, dict) else str(err)
            if code in _AUTH_ERROR_CODES:
                raise AuthError(f"arista eAPI auth error: {msg}")
            raise DriverError(f"arista eAPI error (code={code}): {msg}")
        result = payload.get("result")
        if not isinstance(result, list):
            raise DriverError(f"arista eAPI: missing 'result' list: {payload!r}")
        return result

    # ---------- onboarding ----------

    async def test_credentials(self) -> TestResult:
        start = time.monotonic()
        try:
            result = await self._run_cmds(["show version"], fmt="json")
        except AuthError as exc:
            return TestResult(
                ok=False,
                latency_ms=(time.monotonic() - start) * 1000.0,
                platform_version=None,
                error=str(exc),
            )
        except (ReachabilityError, DriverError) as exc:
            return TestResult(
                ok=False,
                latency_ms=(time.monotonic() - start) * 1000.0,
                platform_version=None,
                error=str(exc),
            )
        latency = (time.monotonic() - start) * 1000.0
        version = _extract_version(result[0]) if result else None
        return TestResult(ok=True, latency_ms=latency, platform_version=version)

    async def discover(self) -> DiscoveryResult:
        hostname = await self._get_hostname()
        ports = await self.get_ports()
        running = await self.get_running_config()
        return DiscoveryResult(
            hostname=hostname,
            ports=tuple(ports),
            running_config=running,
            services={"lldp": True},
        )

    # ---------- read ----------

    async def reachable(self) -> bool:
        try:
            await self._run_cmds(["show version"], fmt="json")
            return True
        except (ReachabilityError, AuthError, DriverError):
            return False

    async def _get_hostname(self) -> str:
        try:
            result = await self._run_cmds(["show hostname"], fmt="json")
        except DriverError:
            return ""
        if not result or not isinstance(result[0], dict):
            return ""
        hostname = result[0].get("hostname")
        return hostname if isinstance(hostname, str) else ""

    async def get_running_config(self) -> str:
        result = await self._run_cmds(["show running-config"], fmt="text")
        if not result or not isinstance(result[0], dict):
            return ""
        output = result[0].get("output")
        return output if isinstance(output, str) else ""

    async def backup_config(self) -> str:
        cfg = await self.get_running_config()
        return cfg if cfg else "! arista: empty running-config\n"

    async def get_ports(self) -> list[PortState]:
        result = await self._run_cmds(
            ["show interfaces", "show interfaces switchport"],
            fmt="json",
        )
        if len(result) < 2:
            return []
        interfaces = _parse_interfaces(result[0])
        switchport = _parse_switchport(result[1])
        return _merge_port_state(interfaces, switchport)

    async def get_neighbors(self, port: str | None = None) -> list[Neighbor]:
        try:
            result = await self._run_cmds(["show lldp neighbors detail"], fmt="json")
        except DriverError:
            return []
        if not result:
            return []
        neighbors = _parse_lldp(result[0])
        if port is None:
            return neighbors
        # Exact-match the local port encoded in the system_description prefix.
        return [n for n in neighbors if lldp.local_port_matches(n.system_description, port)]

    # ---------- write ----------

    async def render_change(self, port: str, change: PortChange) -> ConfigDiff:
        session_name = f"nb-{uuid.uuid4().hex[:8]}"
        cmds = _build_change_commands(port, change)
        raw_before = f"interface {port}\n  ! (previous state not captured)\n"
        raw_after = "\n".join(cmds) + "\n"
        summary = f"Update {port}"
        return ConfigDiff(
            summary=summary,
            raw_before=raw_before,
            raw_after=raw_after,
            commands=tuple(cmds),
            metadata={_SESSION_KEY: session_name},
        )

    async def apply_change(
        self,
        diff: ConfigDiff,
        *,
        confirm_seconds: int = 60,
    ) -> ApplyResult:
        session_name = diff.metadata.get(_SESSION_KEY)
        if not session_name:
            return ApplyResult(
                success=False,
                confirm_token=None,
                confirm_deadline_at=None,
                error="ConfigDiff.metadata missing 'session_name'",
            )
        # Build the eAPI command list: enter config session, run the change,
        # then commit with a timer (auto-rollback if not confirmed).
        timer = _format_commit_timer(confirm_seconds)
        cmds: list[object] = [
            self._enable_cmd(),
            f"configure session {session_name}",
            *diff.commands,
            f"commit timer {timer}",
        ]
        try:
            await self._run_cmds(cmds, fmt="json")
        except (AuthError, ReachabilityError, DriverError) as exc:
            return ApplyResult(
                success=False,
                confirm_token=None,
                confirm_deadline_at=None,
                error=str(exc),
            )
        return ApplyResult(
            success=True,
            confirm_token=session_name,
            confirm_deadline_at=time.time() + confirm_seconds,
            error=None,
        )

    async def confirm(self, apply_token: str) -> None:
        await self._run_cmds(
            [self._enable_cmd(), f"configure session {apply_token}", "commit"],
            fmt="json",
        )

    async def revert(self, apply_token: str) -> None:
        await self._run_cmds(
            [self._enable_cmd(), f"configure session {apply_token}", "abort"],
            fmt="json",
        )


# ---------------------------------------------------------------------------
# parsers — private, pure, easy to unit-test
# ---------------------------------------------------------------------------


def _extract_version(show_version_row: object) -> str | None:
    """Pull ``modelName + version`` out of a ``show version`` JSON row."""
    if not isinstance(show_version_row, dict):
        return None
    model = show_version_row.get("modelName") or show_version_row.get("model")
    version = show_version_row.get("version")
    parts = [str(p) for p in (model, version) if p]
    return " ".join(parts) if parts else None


def _parse_interfaces(payload: object) -> dict[str, PortState]:
    """Convert ``show interfaces`` JSON into a name → PortState map.

    Switchport (vlan) fields default to None here; they're filled in by
    ``_parse_switchport`` and merged in ``_merge_port_state``.
    """
    if not isinstance(payload, dict):
        return {}
    interfaces_obj = payload.get("interfaces")
    if not isinstance(interfaces_obj, dict):
        return {}
    out: dict[str, PortState] = {}
    for name, raw in interfaces_obj.items():
        if not isinstance(raw, dict):
            continue
        line_proto = str(raw.get("lineProtocolStatus", "")).lower()
        iface_status = str(raw.get("interfaceStatus", "")).lower()
        link_up = line_proto == "up"
        admin_up = iface_status != "disabled"
        # bandwidth is in bits/sec when present
        bandwidth_raw = raw.get("bandwidth")
        speed_mbps: int | None = None
        if isinstance(bandwidth_raw, (int, float)) and bandwidth_raw > 0:
            speed_mbps = int(bandwidth_raw // 1_000_000)
        duplex = raw.get("duplex")
        duplex_norm: str | None = None
        if isinstance(duplex, str):
            lower = duplex.lower()
            if "full" in lower:
                duplex_norm = "full"
            elif "half" in lower:
                duplex_norm = "half"
        mac = raw.get("physicalAddress")
        mtu = raw.get("mtu")
        description = raw.get("description") or ""
        out[name] = PortState(
            name=name,
            admin_up=admin_up,
            link_up=link_up,
            speed_mbps=speed_mbps,
            duplex=cast("None | str", duplex_norm),  # type: ignore[assignment]
            mac=mac if isinstance(mac, str) else None,
            mtu=int(mtu) if isinstance(mtu, (int, float)) else None,
            untagged_vlan=None,
            tagged_vlans=(),
            description=description if isinstance(description, str) else "",
            host_model="",
            bmc_ip="",
            notes="",
            services={},
        )
    return out


def _parse_switchport(payload: object) -> dict[str, dict[str, object]]:
    """Pull per-port VLAN info from ``show interfaces switchport``."""
    if not isinstance(payload, dict):
        return {}
    switchports = payload.get("switchports")
    if not isinstance(switchports, dict):
        return {}
    out: dict[str, dict[str, object]] = {}
    for name, raw in switchports.items():
        if not isinstance(raw, dict):
            continue
        sp = raw.get("switchportInfo")
        if not isinstance(sp, dict):
            continue
        out[name] = {
            "access_vlan": sp.get("accessVlanId"),
            "native_vlan": sp.get("trunkingNativeVlanId"),
            "trunk_allowed": sp.get("trunkAllowedVlans"),
            "mode": sp.get("mode"),
        }
    return out


def _merge_port_state(
    interfaces: dict[str, PortState],
    switchport: dict[str, dict[str, object]],
) -> list[PortState]:
    """Overlay switchport VLAN data onto base interface state."""
    out: list[PortState] = []
    for name, base in interfaces.items():
        sp = switchport.get(name)
        if sp is None:
            out.append(base)
            continue
        mode = sp.get("mode")
        if isinstance(mode, str) and "trunk" in mode.lower():
            untagged = _coerce_int(sp.get("native_vlan"))
            tagged = _parse_trunk_allowed(sp.get("trunk_allowed"))
        else:
            untagged = _coerce_int(sp.get("access_vlan"))
            tagged = ()
        # Frozen dataclass — recreate with overlay.
        out.append(
            PortState(
                name=base.name,
                admin_up=base.admin_up,
                link_up=base.link_up,
                speed_mbps=base.speed_mbps,
                duplex=base.duplex,
                mac=base.mac,
                mtu=base.mtu,
                untagged_vlan=untagged,
                tagged_vlans=tagged,
                description=base.description,
                host_model=base.host_model,
                bmc_ip=base.bmc_ip,
                notes=base.notes,
                services=base.services,
            )
        )
    return out


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):  # bool is int subclass — exclude
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _parse_trunk_allowed(value: object) -> tuple[int, ...]:
    """Parse '1-4,10,20' style trunk-allowed strings into a vlan tuple.

    Returns empty on 'ALL', 'NONE', or unparseable inputs — UI shouldn't
    pretend it knows the full vlan set.
    """
    if not isinstance(value, str):
        return ()
    normalized = value.strip().upper()
    if normalized in ("ALL", "NONE", ""):
        return ()
    vlans: list[int] = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            try:
                lo, hi = (int(x) for x in token.split("-", 1))
            except ValueError:
                continue
            vlans.extend(range(lo, hi + 1))
        elif token.isdigit():
            vlans.append(int(token))
    return tuple(vlans)


def _parse_lldp(payload: object) -> list[Neighbor]:
    """Parse ``show lldp neighbors detail`` JSON.

    The local-port name is stored in ``Neighbor.system_description`` prefix
    so ``get_neighbors(port=...)`` can filter on it without adding a new
    schema field. Format: ``[<local_port>] <remote system description>``.
    """
    if not isinstance(payload, dict):
        return []
    table = payload.get("lldpNeighbors")
    if not isinstance(table, dict):
        return []
    out: list[Neighbor] = []
    for local_port, raw in table.items():
        if not isinstance(raw, dict):
            continue
        neighbors_list = raw.get("lldpNeighborInfo")
        if not isinstance(neighbors_list, list):
            continue
        for entry in neighbors_list:
            if not isinstance(entry, dict):
                continue
            chassis_raw = entry.get("chassisId")
            chassis_id = chassis_raw.strip() if isinstance(chassis_raw, str) else ""
            port_id_raw = entry.get("neighborInterfaceInfo", {})
            port_id = ""
            if isinstance(port_id_raw, dict):
                pid = port_id_raw.get("interfaceId") or port_id_raw.get("interfaceIdName")
                if isinstance(pid, str):
                    port_id = pid.strip()
            sys_name = entry.get("systemName")
            sys_desc = entry.get("systemDescription")
            desc_prefix = lldp.encode_local_port_prefix(local_port)
            desc_body = sys_desc if isinstance(sys_desc, str) else ""
            out.append(
                Neighbor(
                    chassis_id=chassis_id,
                    port_id=port_id,
                    system_name=sys_name if isinstance(sys_name, str) else None,
                    system_description=desc_prefix + desc_body,
                )
            )
    return out


def _build_change_commands(port: str, change: PortChange) -> list[str]:
    """CLI command list for a PortChange — order matters on EOS.

    Description first (cosmetic, can't fail), then mode (access vs trunk),
    then the vlan body. Trunk and access are mutually exclusive on a port,
    so a PortChange specifying both ``untagged_vlan`` and ``tagged_vlans``
    means: trunk mode, with native = untagged_vlan, allowed = tagged_vlans.
    """
    cmds: list[str] = [f"interface {port}"]
    if change.description is not None:
        cmds.append(f"  description {change.description}")
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


def _format_commit_timer(seconds: int) -> str:
    """Render an EOS commit-timer value as ``H:MM:SS``."""
    s = max(1, int(seconds))
    hours, rem = divmod(s, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"
