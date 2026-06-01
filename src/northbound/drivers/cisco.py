"""Cisco driver — NX-OS (NX-API JSON-RPC over HTTPS) + IOS/IOS-XE (SSH CLI).

One driver, two backends, selected by ``ConnectionParams.prefer_native_api``:

* ``prefer_native_api=True`` → **NX-API** path (Cisco Nexus / NX-OS).
  JSON-RPC POST to ``https://<host>/ins`` with body::

      {"jsonrpc": "2.0", "method": "cli", "params": {"cmd": "show ...",
       "version": 1}, "id": 1}

  ``method="cli"`` returns structured JSON in ``result.body``; ``cli_ascii``
  returns raw text in ``result.msg``. HTTP Basic auth. This is the primary
  path and mirrors the Arista eAPI driver closely.

* ``prefer_native_api=False`` → **SSH CLI** path (classic Cisco IOS / IOS-XE).
  ``show`` commands run over ``SshClient`` and text output is returned. The
  SSH path is a thinner fallback: ``test_credentials`` / ``reachable`` /
  ``get_running_config`` / ``backup_config`` / ``get_ports`` are implemented;
  structured reads that depend on NX-API JSON (``get_neighbors``) and the
  commit-confirm write path are NX-API-only and documented as such.

Write path (NX-API): NX-OS has **no device-armed timed rollback** — there is
no ``rollback ... delay`` command. The commit-confirm *window* is enforced at
the application layer by Northbound's reconciler (``ChangeRequest`` carries a
``confirm_deadline_at``; ``services/reconciler._fail_confirm_expired`` calls
``driver.revert`` when the window lapses). The device side only provides a
named *checkpoint* as the rollback target. ``render_change`` mints a checkpoint
name into ``ConfigDiff.metadata['checkpoint_name']`` (same shape as Arista's
session name). ``apply_change`` creates the checkpoint (``checkpoint <name>``)
then applies the config; ``confirm`` deletes the checkpoint (``no checkpoint
<name>`` → change permanent); ``revert`` rolls back to the checkpoint
immediately (``rollback running-config checkpoint <name>``) then drops it.
``capabilities.supports_commit_confirm`` is True because Northbound provides
confirm semantics via checkpoint + reconciler — but the timer is app-enforced,
not device-armed.

Only the JSON / CLI contract lives here — every byte of HTTP goes through
``HttpxClient`` and every SSH command through ``SshClient``. This driver
never imports ``httpx`` or ``asyncssh`` directly.

NX-API JSON shapes (per Cisco NX-API CLI reference):
    show interface          → {"TABLE_interface": {"ROW_interface": [ ... ]}}
    show vlan               → {"TABLE_vlanbrief": {"ROW_vlanbrief": [ ... ]}}
    show interface switchport → {"TABLE_interface": {"ROW_interface": [ ... ]}}
    show lldp neighbors detail → {"TABLE_nbor_detail": {"ROW_nbor_detail": [...]}}
Tables collapse to a bare object (not a list) when there is exactly one row;
``_rows`` normalizes both forms. Field names are taken from the published
NX-API docs; where a key's exact spelling is uncertain the parsers read
several known aliases defensively (see per-helper docstrings).
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from northbound._lib import lldp
from northbound._lib.transport.asyncssh_client import SshClient, SshParams
from northbound._lib.transport.httpx_client import HttpxClient, HttpxParams
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

# NX-API JSON-RPC error codes that map to AuthError. NX-API returns HTTP 401
# for bad basic-auth before JSON-RPC runs, but some setups answer 200 + a
# JSON-RPC error object instead — handle both.
_AUTH_ERROR_CODES = {-32004, -32603}  # permission / internal-auth (defensive)

# ConfigDiff metadata key for the rollback checkpoint name.
_CHECKPOINT_KEY = "checkpoint_name"


@register
class CiscoDriver(Driver):
    """Cisco NX-OS (NX-API) and IOS/IOS-XE (SSH)."""

    platform_id = "cisco"
    display_name = "Cisco IOS / NX-OS"
    capabilities = DriverCapabilities(
        writable=True,
        supports_commit_confirm=True,
        native_api_available=True,
        # Reads go via NX-API / SSH; no SNMP read path is wired into this driver.
        # The SNMP transport exists and is live-validated but is unused here, so
        # this is reported honestly as False rather than advertised to the UI.
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
        http: HttpxClient | None = None,
        ssh: SshClient | None = None,
    ) -> None:
        super().__init__(conn, creds)
        self._use_native = conn.prefer_native_api
        # Only build the transport we actually use; injected transports win.
        self._http = (
            http if http is not None else (self._build_http() if self._use_native else None)
        )
        self._ssh = ssh if ssh is not None else (None if self._use_native else self._build_ssh())

    async def aclose(self) -> None:
        """Close the NX-API http transport if one is held. Idempotent."""
        http = self._http
        if http is not None:
            self._http = None
            await http.aclose()

    # ---------- transport plumbing ----------

    def _build_http(self) -> HttpxClient:
        port = self._conn.port or 443
        base_url = f"https://{self._conn.host}:{port}"
        return HttpxClient(
            HttpxParams(
                base_url=base_url,
                timeout_seconds=self._conn.timeout_seconds,
                max_concurrency=self.capabilities.max_concurrency,
                verify_tls=False,  # lab default; production wires this off conn
            )
        )

    def _build_ssh(self) -> SshClient:
        return SshClient(
            SshParams(
                host=self._conn.host,
                username=self._creds.username or "",
                port=self._conn.port or 22,
                password=self._creds.password,
                private_key=self._creds.ssh_private_key,
                timeout_seconds=self._conn.timeout_seconds,
                max_concurrency=1,
            )
        )

    def _auth_header(self) -> dict[str, str]:
        username = self._creds.username or ""
        password = self._creds.password or ""
        return HttpxClient.basic_auth_header(username, password)

    def _nxapi_headers(self) -> dict[str, str]:
        """Basic-auth + the NX-API JSON-RPC content type.

        NX-OS REQUIRES ``Content-Type: application/json-rpc`` for the JSON-RPC
        endpoint; the httpx default of ``application/json`` is rejected with
        HTTP 400 "Invalid request" for several methods (verified live against
        NX-OS 7.3 Titanium — ``cli_ascii``/config calls failed under
        application/json). Always send the explicit type.
        """
        return {**self._auth_header(), "Content-Type": "application/json-rpc"}

    def _require_http(self) -> HttpxClient:
        if self._http is None:
            raise NotSupported(
                "cisco: NX-API transport unavailable (SSH-only mode); "
                "this operation requires prefer_native_api=True"
            )
        return self._http

    def _require_ssh(self) -> SshClient:
        if self._ssh is None:
            raise NotSupported("cisco: SSH transport unavailable (NX-API mode)")
        return self._ssh

    async def _nxapi_cli(self, cmd: str, *, ascii_output: bool = False) -> object:
        """Run one NX-API ``cli`` command. Returns ``result.body`` (json) or
        ``result.msg`` text (ascii).

        Raises:
            AuthError: HTTP 401 or NX-API auth error code.
            ReachabilityError: connection refused / DNS / timeout.
            DriverError: any other NX-API failure.
        """
        http = self._require_http()
        method = "cli_ascii" if ascii_output else "cli"
        body = {
            "jsonrpc": "2.0",
            "method": method,
            "params": {"cmd": cmd, "version": 1},
            "id": 1,
        }
        try:
            response = await http.post("/ins", headers=self._nxapi_headers(), json=body)
        except Exception as exc:  # transport-level failures
            raise ReachabilityError(f"cisco NX-API transport error: {exc}") from exc

        if response.status_code == 401:
            raise AuthError("cisco NX-API returned 401")
        if response.status_code >= 400:
            raise DriverError(f"cisco NX-API HTTP {response.status_code}: {response.text}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise DriverError(f"cisco NX-API: non-dict response: {payload!r}")
        if "error" in payload:
            err = payload["error"]
            code = err.get("code") if isinstance(err, dict) else None
            msg = err.get("message") if isinstance(err, dict) else str(err)
            if code in _AUTH_ERROR_CODES:
                raise AuthError(f"cisco NX-API auth error: {msg}")
            raise DriverError(f"cisco NX-API error (code={code}): {msg}")
        result = payload.get("result")
        if result is None:
            # NX-OS returns null result for commands with no output (e.g.
            # successful config lines). Treat as an empty body.
            return {} if not ascii_output else ""
        if not isinstance(result, dict):
            raise DriverError(f"cisco NX-API: unexpected 'result': {result!r}")
        if ascii_output:
            msg = result.get("msg")
            return msg if isinstance(msg, str) else ""
        body_obj = result.get("body")
        return body_obj if body_obj is not None else {}

    async def _nxapi_cli_config(self, lines: list[str]) -> None:
        """Apply config commands via the NX-API JSON-RPC command ARRAY.

        NX-API REJECTS a `` ; ``-joined single ``cli`` string with code -32602
        "Request contains invalid special characters" (verified live on NX-OS
        7.3). The correct form is an ARRAY of JSON-RPC objects — one command per
        object, ``id`` 1..n — run sequentially under ``configure terminal``.

        Atomicity is NOT device-guaranteed: a mid-list failure can leave a
        partially-applied interface. The rollback safety net is the
        ``checkpoint`` taken in ``apply_change`` immediately before this call;
        ``revert`` restores it (and the reconciler does so on a missed window).

        Error surfacing: NX-OS returns HTTP 500 with a per-command result array
        on partial failure, so we parse the body regardless of status code and
        raise on the first per-command (or top-level) error rather than swallow
        a half-applied change.

        Raises:
            AuthError / ReachabilityError / DriverError on failure.
        """
        cmds = ["configure terminal", *lines]
        body = [
            {"jsonrpc": "2.0", "method": "cli", "params": {"cmd": c, "version": 1}, "id": i + 1}
            for i, c in enumerate(cmds)
        ]
        http = self._require_http()
        try:
            response = await http.post("/ins", headers=self._nxapi_headers(), json=body)
        except Exception as exc:
            raise ReachabilityError(f"cisco NX-API transport error: {exc}") from exc

        if response.status_code == 401:
            raise AuthError("cisco NX-API returned 401")
        try:
            payload = response.json()
        except Exception as exc:  # non-JSON body on a hard error
            raise DriverError(f"cisco NX-API HTTP {response.status_code}: {response.text}") from exc
        _raise_for_config_errors(payload)

    # ---------- onboarding ----------

    async def test_credentials(self) -> TestResult:
        start = time.monotonic()
        try:
            if self._use_native:
                body = await self._nxapi_cli("show version")
                version = _extract_version(body)
            else:
                text = await self._ssh_run("show version")
                version = _extract_version_text(text)
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
        return TestResult(ok=True, latency_ms=latency, platform_version=version)

    async def discover(self) -> DiscoveryResult:
        hostname = await self._get_hostname()
        ports = await self.get_ports()
        running = await self.get_running_config()
        return DiscoveryResult(
            hostname=hostname,
            ports=tuple(ports),
            running_config=running,
            services={"lldp": self.capabilities.supports_lldp},
        )

    # ---------- read ----------

    async def reachable(self) -> bool:
        try:
            if self._use_native:
                await self._nxapi_cli("show clock")
            else:
                await self._ssh_run("show clock")
            return True
        except (ReachabilityError, AuthError, DriverError, NotSupported):
            return False

    async def _get_hostname(self) -> str:
        if self._use_native:
            try:
                body = await self._nxapi_cli("show hostname")
            except (DriverError, ReachabilityError, AuthError):
                return ""
            if isinstance(body, dict):
                name = body.get("hostname") or body.get("host_name")
                if isinstance(name, str):
                    return name.strip()
            return ""
        try:
            text = await self._ssh_run("show running-config | include ^hostname")
        except (DriverError, ReachabilityError, AuthError, NotSupported):
            return ""
        return _parse_hostname_text(text)

    async def get_running_config(self) -> str:
        if self._use_native:
            text = await self._nxapi_cli("show running-config", ascii_output=True)
            return text if isinstance(text, str) else ""
        return await self._ssh_run("show running-config")

    async def backup_config(self) -> str:
        cfg = await self.get_running_config()
        return cfg if cfg else "! cisco: empty running-config\n"

    async def get_ports(self) -> list[PortState]:
        if self._use_native:
            interfaces = _parse_interfaces(await self._nxapi_cli("show interface"))
            switchport = _parse_switchport(await self._nxapi_cli("show interface switchport"))
            return _merge_port_state(interfaces, switchport)
        # SSH fallback: parse "show interfaces status" text into a coarse view.
        text = await self._ssh_run("show interfaces status")
        return _parse_interfaces_status_text(text)

    async def get_neighbors(self, port: str | None = None) -> list[Neighbor]:
        if self._use_native:
            try:
                body = await self._nxapi_cli("show lldp neighbors detail")
            except (DriverError, ReachabilityError, AuthError):
                return []
            neighbors = _parse_lldp(body)
        else:
            # IOS/IOS-XE SSH path: parse `show lldp neighbors detail` text via the
            # maintained ntc-templates TextFSM template (live-validated vs IOSvL2).
            try:
                text = await self._ssh_run("show lldp neighbors detail")
            except (DriverError, ReachabilityError, AuthError, NotSupported):
                return []
            neighbors = _parse_lldp_text(text)
        if port is None:
            return neighbors
        return [n for n in neighbors if lldp.local_port_matches(n.system_description, port)]

    async def _ssh_run(self, command: str) -> str:
        ssh = self._require_ssh()
        try:
            return await ssh.run(command)
        except Exception as exc:  # asyncssh raises a broad set; classify by msg
            raise _classify_ssh_error(exc) from exc

    # ---------- write (NX-API only) ----------

    async def render_change(self, port: str, change: PortChange) -> ConfigDiff:
        checkpoint = f"nb-{uuid.uuid4().hex[:8]}"
        cmds = _build_change_commands(port, change)
        raw_before = f"interface {port}\n  ! (previous state not captured)\n"
        raw_after = "\n".join(cmds) + "\n"
        return ConfigDiff(
            summary=f"Update {port}",
            raw_before=raw_before,
            raw_after=raw_after,
            commands=tuple(cmds),
            metadata={_CHECKPOINT_KEY: checkpoint},
        )

    async def apply_change(
        self,
        diff: ConfigDiff,
        *,
        confirm_seconds: int = 60,
    ) -> ApplyResult:
        if not self._use_native:
            raise NotSupported(
                "cisco: commit-confirm write path requires NX-API "
                "(prefer_native_api=True); SSH path is read-only"
            )
        checkpoint = diff.metadata.get(_CHECKPOINT_KEY)
        if not checkpoint:
            return ApplyResult(
                success=False,
                confirm_token=None,
                confirm_deadline_at=None,
                error="ConfigDiff.metadata missing 'checkpoint_name'",
            )
        # Snapshot the running-config into a named checkpoint, then apply the
        # change body as a single atomic NX-API request. There is NO device-side
        # timed rollback on NX-OS; the confirm window is enforced by Northbound's
        # reconciler (confirm_deadline_at below). confirm() deletes the
        # checkpoint (permanent); revert() rolls back to it.
        try:
            await self._nxapi_cli(f"checkpoint {checkpoint}")
            await self._nxapi_cli_config(_config_lines(diff.commands))
        except (AuthError, ReachabilityError, DriverError) as exc:
            return ApplyResult(
                success=False,
                confirm_token=None,
                confirm_deadline_at=None,
                error=str(exc),
            )
        return ApplyResult(
            success=True,
            confirm_token=checkpoint,
            confirm_deadline_at=time.time() + confirm_seconds,
            error=None,
        )

    async def confirm(self, apply_token: str) -> None:
        if not self._use_native:
            raise NotSupported("cisco: confirm requires NX-API (prefer_native_api=True)")
        # Drop the checkpoint → the applied change becomes permanent. NX-OS has
        # no armed timer to cancel; the confirm window was reconciler-enforced.
        await self._nxapi_cli(f"no checkpoint {apply_token}")

    async def revert(self, apply_token: str) -> None:
        if not self._use_native:
            raise NotSupported("cisco: revert requires NX-API (prefer_native_api=True)")
        # Immediate rollback to the checkpoint, then clean up the checkpoint.
        await self._nxapi_cli(f"rollback running-config checkpoint {apply_token}")
        await self._nxapi_cli(f"no checkpoint {apply_token}")


# ---------------------------------------------------------------------------
# parsers — private, pure, easy to unit-test
# ---------------------------------------------------------------------------


def _rows(table: object, table_key: str, row_key: str) -> list[dict[str, object]]:
    """Normalize an NX-API ``TABLE_x / ROW_x`` block into a list of row dicts.

    NX-OS collapses a single-row table to a bare object instead of a list,
    so both shapes must be handled. Returns ``[]`` on any unexpected shape.
    """
    if not isinstance(table, dict):
        return []
    tbl = table.get(table_key)
    if not isinstance(tbl, dict):
        return []
    rows = tbl.get(row_key)
    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict)]
    if isinstance(rows, dict):
        return [rows]
    return []


def _extract_version(body: object) -> str | None:
    """Pull a version string out of a ``show version`` NX-API body.

    NX-API keys are ``chassis_id`` / ``kickstart_ver_str`` (older) or
    ``nxos_ver_str`` (newer). Read several known aliases defensively.
    """
    if not isinstance(body, dict):
        return None
    model = body.get("chassis_id") or body.get("rr_sys_ver")
    version = body.get("nxos_ver_str") or body.get("kickstart_ver_str") or body.get("sys_ver_str")
    parts = [str(p) for p in (model, version) if p]
    return " ".join(parts) if parts else None


def _extract_version_text(text: str) -> str | None:
    """Best-effort version extraction from ``show version`` CLI text (IOS)."""
    for line in text.splitlines():
        lower = line.lower()
        if "version" in lower and ("cisco ios" in lower or "software" in lower):
            return line.strip()
    return None


def _parse_hostname_text(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("hostname "):
            return stripped.split(None, 1)[1].strip()
    return ""


def _parse_interfaces(body: object) -> dict[str, PortState]:
    """Convert ``show interface`` (NX-API JSON) into a name → PortState map.

    Reads ``TABLE_interface/ROW_interface``. Switchport VLAN fields default
    to None here; they're overlaid by ``_parse_switchport`` in
    ``_merge_port_state``. NX-API field names: ``interface``, ``state``
    (oper up/down), ``admin_state`` (up/down), ``eth_speed`` / ``eth_bw``,
    ``eth_duplex``, ``eth_hw_addr`` / ``eth_bia_addr``, ``eth_mtu``,
    ``desc``.
    """
    out: dict[str, PortState] = {}
    for raw in _rows(body, "TABLE_interface", "ROW_interface"):
        name = raw.get("interface")
        if not isinstance(name, str) or not name:
            continue
        oper = str(raw.get("state", "")).lower()
        admin = str(raw.get("admin_state", "")).lower()
        link_up = oper == "up"
        # admin_state="down" means shutdown; missing → assume up
        admin_up = admin != "down"
        speed_mbps = _parse_speed(raw.get("eth_speed"), raw.get("eth_bw"))
        duplex = _normalize_duplex(raw.get("eth_duplex"))
        mac_raw = raw.get("eth_hw_addr") or raw.get("eth_bia_addr")
        mac = mac_raw if isinstance(mac_raw, str) else None
        mtu = _coerce_int(raw.get("eth_mtu"))
        desc_raw = raw.get("desc")
        description = desc_raw if isinstance(desc_raw, str) else ""
        out[name] = PortState(
            name=name,
            admin_up=admin_up,
            link_up=link_up,
            speed_mbps=speed_mbps,
            duplex=duplex,
            mac=mac,
            mtu=mtu,
            untagged_vlan=None,
            tagged_vlans=(),
            description=description,
            host_model="",
            bmc_ip="",
            notes="",
            services={},
        )
    return out


def _parse_switchport(body: object) -> dict[str, dict[str, object]]:
    """Pull per-port VLAN info from ``show interface switchport`` (NX-API).

    Reads ``TABLE_interface/ROW_interface``. NX-API field names:
    ``interface``, ``oper_mode`` (access/trunk), ``access_vlan``,
    ``native_vlan``, ``trunk_vlans`` (allowed list string).
    """
    out: dict[str, dict[str, object]] = {}
    for raw in _rows(body, "TABLE_interface", "ROW_interface"):
        name = raw.get("interface")
        if not isinstance(name, str) or not name:
            continue
        mode = raw.get("oper_mode") or raw.get("sw_mode")
        out[name] = {
            "access_vlan": raw.get("access_vlan"),
            "native_vlan": raw.get("native_vlan"),
            "trunk_allowed": raw.get("trunk_vlans"),
            "mode": mode,
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


# Down/disabled status keywords from `show interfaces status` (used only to set
# admin_up/link_up from the maintained ntc-templates ``status`` field).
_IFSTATUS_DOWN = {"disabled", "disable", "suspended", "err-disabled", "errdisabled"}


def _parse_interfaces_status_text(text: str) -> list[PortState]:
    """Parse ``show interfaces status`` via the maintained ntc-templates
    TextFSM template (IOS SSH fallback).

    We do NOT hand-roll the column layout: the "Name" column is optional and
    usually blank, which shifts every later column and silently dropped the
    VLAN in a hand-written parser (caught live on IOSvL2). ``ntc-templates``
    (Network-to-Code) carries community-maintained templates tested against real
    devices across IOS versions, and returns ``port/name/status/vlan_id/duplex/
    speed/type``. We map those onto PortState; on any parse failure we return
    ``[]`` rather than raise (the SSH path is a best-effort fallback).
    """
    try:
        from ntc_templates.parse import parse_output

        rows = parse_output(platform="cisco_ios", command="show interfaces status", data=text)
    except Exception:  # missing template / textfsm parse error — degrade gracefully
        return []

    out: list[PortState] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("port") or "").strip()
        if not name:
            continue
        status = str(row.get("status") or "").lower()
        out.append(
            PortState(
                name=name,
                admin_up=status not in _IFSTATUS_DOWN,
                link_up=status == "connected",
                speed_mbps=None,
                duplex=_normalize_duplex(row.get("duplex")),
                mac=None,
                mtu=None,
                untagged_vlan=_coerce_int(row.get("vlan_id")),
                tagged_vlans=(),
                description=str(row.get("name") or ""),
                host_model="",
                bmc_ip="",
                notes="",
                services={},
            )
        )
    return out


def _parse_lldp(body: object) -> list[Neighbor]:
    """Parse ``show lldp neighbors detail`` (NX-API JSON).

    Reads ``TABLE_nbor_detail/ROW_nbor_detail``. NX-API field names:
    ``chassis_id``, ``l_port_id`` (local port), ``port_id`` (remote port),
    ``sys_name``, ``sys_desc``. The local-port name is encoded into the
    ``Neighbor.system_description`` prefix (``[<local_port>] ...``) so
    ``get_neighbors(port=...)`` can filter without a new schema field —
    mirrors the Arista driver. Chassis/port IDs are run through
    ``_lib.lldp`` normalizers.
    """
    out: list[Neighbor] = []
    for raw in _rows(body, "TABLE_nbor_detail", "ROW_nbor_detail"):
        chassis_raw = raw.get("chassis_id")
        chassis_id = lldp.normalize_chassis_id(chassis_raw) if isinstance(chassis_raw, str) else ""
        remote_port_raw = raw.get("port_id")
        remote_port = (
            lldp.normalize_port_id(remote_port_raw) if isinstance(remote_port_raw, str) else ""
        )
        local_port_raw = raw.get("l_port_id")
        local_port = local_port_raw if isinstance(local_port_raw, str) else ""
        sys_name = raw.get("sys_name")
        sys_desc = raw.get("sys_desc")
        desc_prefix = lldp.encode_local_port_prefix(local_port)
        desc_body = sys_desc if isinstance(sys_desc, str) else ""
        out.append(
            Neighbor(
                chassis_id=chassis_id,
                port_id=remote_port,
                system_name=sys_name if isinstance(sys_name, str) else None,
                system_description=(desc_prefix + desc_body) or None,
            )
        )
    return out


def _parse_lldp_text(text: str) -> list[Neighbor]:
    """Parse ``show lldp neighbors detail`` (IOS/IOS-XE SSH) via ntc-templates.

    The maintained ``cisco_ios_show_lldp_neighbors_detail`` TextFSM template
    yields LOCAL_INTERFACE / CHASSIS_ID / NEIGHBOR_PORT_ID / NEIGHBOR_NAME /
    NEIGHBOR_DESCRIPTION. The local port is encoded into the
    ``system_description`` ``[<local_port>] `` prefix (same convention as the
    NX-API path) so ``get_neighbors(port=...)`` filters identically. Degrades to
    ``[]`` on a parse failure (best-effort SSH path).
    """
    try:
        from ntc_templates.parse import parse_output

        rows = parse_output(platform="cisco_ios", command="show lldp neighbors detail", data=text)
    except Exception:
        return []

    out: list[Neighbor] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        local = str(row.get("local_interface") or "").strip()
        chassis_raw = str(row.get("chassis_id") or "").strip()
        remote_port = str(
            row.get("neighbor_port_id") or row.get("neighbor_interface") or ""
        ).strip()
        sys_name = str(row.get("neighbor_name") or "").strip()
        desc_body = str(row.get("neighbor_description") or "").strip()
        out.append(
            Neighbor(
                chassis_id=lldp.normalize_chassis_id(chassis_raw) if chassis_raw else "",
                port_id=lldp.normalize_port_id(remote_port) if remote_port else "",
                system_name=sys_name or None,
                system_description=(lldp.encode_local_port_prefix(local) + desc_body) or None,
            )
        )
    return out


def _build_change_commands(port: str, change: PortChange) -> list[str]:
    """Cisco config command list for a PortChange — order matters.

    Description first (cosmetic), then mode (access vs trunk), then the VLAN
    body. A PortChange carrying ``tagged_vlans`` means trunk mode with native
    = untagged_vlan and allowed = tagged_vlans; otherwise access mode with
    access vlan = untagged_vlan. ``tagged_vlans`` is declarative — the desired
    full allowed set — so we emit ``switchport trunk allowed vlan {allowed}``
    (replace), NOT ``add`` (which would only accumulate and never remove).
    Matches the Arista driver's semantics.
    """
    cmds: list[str] = [f"interface {port}"]
    if change.description is not None:
        cmds.append(f"  description {change.description}")
    if change.tagged_vlans is not None or change.untagged_vlan is not None:
        # Bare ``switchport`` first: on NX-OS (and L3-capable IOS ports) an
        # interface defaults to routed, and ``switchport mode ...`` is rejected
        # with "% Invalid command" until the port is made L2 (verified live on
        # NX-OS 7.3). Idempotent on already-L2 ports.
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


def _config_lines(commands: tuple[str, ...]) -> list[str]:
    """Strip + drop blanks from a rendered command tuple for atomic apply.

    ``configure terminal`` is prepended by ``_nxapi_cli_config`` itself, so
    this returns only the interface/switchport body lines.
    """
    return [c.strip() for c in commands if c.strip()]


def _raise_for_config_errors(payload: object) -> None:
    """Surface any NX-API error from a ``cli`` command-array config response.

    The array form returns a LIST of JSON-RPC response objects (one per
    command); a single-object response is also tolerated. Any object carrying
    an ``error`` raises — we dig ``error.data.msg`` first (the useful detail,
    e.g. "% Invalid command") then fall back to ``error.message``. Raises rather
    than silently swallow a half-applied change.
    """
    entries = payload if isinstance(payload, list) else [payload]
    for entry in entries:
        if not isinstance(entry, dict) or "error" not in entry:
            continue
        err = entry["error"]
        code = err.get("code") if isinstance(err, dict) else None
        data = err.get("data") if isinstance(err, dict) else None
        msg = (
            (data.get("msg") if isinstance(data, dict) else None)
            or (err.get("message") if isinstance(err, dict) else None)
            or str(err)
        )
        if code in _AUTH_ERROR_CODES:
            raise AuthError(f"cisco NX-API auth error: {msg}")
        raise DriverError(f"cisco NX-API config error (code={code}): {str(msg).strip()}")


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):  # bool is an int subclass — exclude
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _parse_speed(eth_speed: object, eth_bw: object) -> int | None:
    """Resolve port speed in Mbps from NX-API ``eth_speed`` / ``eth_bw``.

    ``eth_speed`` is a human string (e.g. ``"10 Gb/s"``, ``"1000 Mb/s"``,
    ``"auto-speed"``). ``eth_bw`` is bandwidth in Kbit/s when present. Prefer
    the explicit speed; fall back to bandwidth.
    """
    if isinstance(eth_speed, str):
        lower = eth_speed.lower()
        digits = "".join(ch for ch in lower if ch.isdigit())
        if digits:
            value = int(digits)
            if "gb" in lower or "g/" in lower:
                return value * 1000
            if "mb" in lower or "m/" in lower:
                return value
    bw = _coerce_int(eth_bw)
    if bw and bw > 0:
        return bw // 1000  # Kbit/s → Mbps
    return None


def _normalize_duplex(value: object) -> Literal["full", "half"] | None:
    if not isinstance(value, str):
        return None
    lower = value.lower()
    if "full" in lower:
        return "full"
    if "half" in lower:
        return "half"
    return None


def _parse_trunk_allowed(value: object) -> tuple[int, ...]:
    """Parse '1-4,10,20' style trunk-allowed strings into a vlan tuple.

    Returns empty on 'ALL', 'NONE', or unparseable input — the UI shouldn't
    pretend it knows the full VLAN set.
    """
    if not isinstance(value, str):
        return ()
    normalized = value.strip().upper()
    if normalized in ("ALL", "NONE", "1-4094", ""):
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


def _classify_ssh_error(exc: BaseException) -> DriverError:
    """Map an asyncssh exception to a canonical driver exception."""
    msg = str(exc).lower()
    if "auth" in msg or "permission denied" in msg:
        return AuthError(f"cisco SSH auth error: {exc}")
    if "connect" in msg or "timed out" in msg or "timeout" in msg or "refused" in msg:
        return ReachabilityError(f"cisco SSH reachability error: {exc}")
    return DriverError(f"cisco SSH error: {exc}")
