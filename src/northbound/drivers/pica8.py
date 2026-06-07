"""Pica8 PicOS driver — NETCONF over SSH (port 830).

Write path uses NETCONF candidate config + ``<commit confirmed/>``. NETCONF
has no named sessions, so the ``apply_token`` is a driver-generated string
stored in ``self._pending_token``; ``confirm`` / ``revert`` only act when
the token matches. This keeps the contract symmetrical with Arista's
named-session model while reflecting the actual protocol.

XML namespace handling: Pica8 surfaces YANG nodes under a vendor namespace
(``http://pica8.com/xorplus/*``). Parsers strip namespaces before reading
element names — easier to grep, easier to test, no functional cost. If we
ever need to round-trip XML back to the device we'd revisit.

Why ncclient and NOT junos-eznc/PyEZ: PicOS borrows the Junos *CLI* but its
NETCONF schema is its own xorplus YANG, not Junos. PyEZ was live-tested
against PicOS-V (2026-06-01) and every Junos RPC it issues was rejected with
"operation not supported by this implementation" (get-software-information,
get-interface-information), facts came back empty, and PyEZ's Junos device
handler even failed to transform PicOS replies. Only the raw NETCONF
transport works — which ncclient (the de-facto Python NETCONF library)
provides directly. So the real-library choice here is ncclient, wrapped by
NetconfClient; the remaining driver code is the irreducible mapping between
PicOS's xorplus XML and our PortState (no library does that).
"""

from __future__ import annotations

import contextlib
import re
import time
import uuid

from lxml import etree  # type: ignore[attr-defined]  # lxml has no stubs; etree is C-extension

from northbound._lib.transport.asyncssh_client import SshClient, SshParams
from northbound._lib.transport.netconf_client import NetconfClient, NetconfParams
from northbound.drivers._protocol_gets import (
    PROTOCOL_GETS,
    STANDALONE_GETS,
    parse_table,
)
from northbound.drivers.base import (
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
    DeviceFacts,
    DiscoveryResult,
    DriverCapabilities,
    L3Change,
    L3Interface,
    MacEntry,
    MgmtService,
    Neighbor,
    OspfChange,
    OspfInterfaceInfo,
    PortChange,
    PortState,
    ProtocolDetail,
    ProtocolStatus,
    ProtocolTable,
    SystemInfo,
    TestResult,
    VlanChange,
    VlanInfo,
    VrfChange,
)

# ConfigDiff metadata keys (kept here to avoid magic strings).
_TOKEN_KEY = "pending_token"
_PORT_KEY = "port_name"  # diff.metadata: target port, for post-write verify
_INTENT_KEY = "intent_json"  # diff.metadata: the PortChange, serialized, for verify


@register
class Pica8Driver(Driver):
    """Pica8 PicOS via NETCONF."""

    platform_id = "pica8"
    display_name = "Pica8 PicOS"
    capabilities = DriverCapabilities(
        writable=True,
        supports_commit_confirm=True,
        native_api_available=True,
        # Reads go via NETCONF; no SNMP read path is wired into this driver. The
        # SNMP transport exists and is live-validated but is unused here, so this
        # is reported honestly as False rather than advertised to the UI.
        supports_snmp_read=False,
        supports_lldp=True,
        max_concurrency=1,
        auth_methods=[AuthMethod.PASSWORD, AuthMethod.SSH_KEY],
        web_ui_url_template="https://{mgmt_ip}/",
    )

    def __init__(
        self,
        conn: ConnectionParams,
        creds: Credentials,
        *,
        netconf: NetconfClient | None = None,
        ssh: SshClient | None = None,
    ) -> None:
        super().__init__(conn, creds)
        self._netconf = netconf if netconf is not None else self._build_netconf()
        # SSH is used only for operational reads the NETCONF data model doesn't
        # expose (the MAC/forwarding table). Built lazily; injectable for tests.
        self._ssh = ssh if ssh is not None else self._build_ssh()
        # Token currently 'live' on the device — set by apply_change.
        self._pending_token: str | None = None

    async def aclose(self) -> None:
        """Close the NETCONF session. Idempotent (NetconfClient.close is)."""
        await self._netconf.close()

    def _build_netconf(self) -> NetconfClient:
        return NetconfClient(
            NetconfParams(
                host=self._conn.host,
                username=self._creds.username or "",
                password=self._creds.password,
                private_key=self._creds.ssh_private_key,
                port=self._conn.port or 830,
                timeout_seconds=self._conn.timeout_seconds,
                hostkey_verify=False,  # lab default
            )
        )

    def _build_ssh(self) -> SshClient:
        # CLI-over-SSH (port 22) for operational reads the NETCONF data model
        # doesn't expose. NOT the NETCONF port (self._conn.port may be 830).
        return SshClient(
            SshParams(
                host=self._conn.host,
                username=self._creds.username or "",
                password=self._creds.password,
                private_key=self._creds.ssh_private_key,
                port=22,
                timeout_seconds=self._conn.timeout_seconds,
            )
        )

    # ---------- onboarding ----------

    async def test_credentials(self) -> TestResult:
        start = time.monotonic()
        try:
            await self._netconf.get_config(source="running")
        except Exception as exc:  # ncclient raises a broad set; classify by msg
            elapsed = (time.monotonic() - start) * 1000.0
            return TestResult(
                ok=False,
                latency_ms=elapsed,
                platform_version=None,
                error=str(exc),
            )
        elapsed = (time.monotonic() - start) * 1000.0
        return TestResult(ok=True, latency_ms=elapsed, platform_version="picos")

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
            await self._netconf.get_config(source="running")
            return True
        except Exception:
            return False

    async def _get_hostname(self) -> str:
        try:
            cfg = await self._netconf.get_config(source="running")
        except Exception:
            return ""
        root = _safe_parse(cfg)
        if root is None:
            return ""
        for el in root.iter():
            if _localname(el.tag) == "hostname" and el.text:
                return el.text.strip()
        return ""

    async def get_running_config(self) -> str:
        try:
            return await self._netconf.get_config(source="running")
        except Exception as exc:
            raise ReachabilityError(f"pica8 get-config failed: {exc}") from exc

    async def backup_config(self) -> str:
        cfg = await self.get_running_config()
        return cfg if cfg else "<empty/>\n"

    async def get_ports(self) -> list[PortState]:
        try:
            cfg = await self._netconf.get_config(source="running")
        except Exception:
            return []
        ports = _parse_interfaces_xml(cfg)
        # NETCONF get-config carries no operational state, so speed/duplex/MAC/
        # link come back empty. Enrich from `show interface` over SSH (one call,
        # all ports). Best-effort: if SSH is unavailable, keep the config view.
        try:
            out = await self._ssh.run('cli -c "show interface"')
            oper = _parse_interface_oper(out)
            ports = [_merge_oper(p, oper.get(p.name)) for p in ports]
        except Exception:
            pass
        return ports

    async def get_neighbors(self, port: str | None = None) -> list[Neighbor]:
        try:
            cfg = await self._netconf.get_config(source="running")
        except Exception:
            return []
        neighbors = _parse_lldp_xml(cfg)
        if port is None:
            return neighbors
        return [n for n in neighbors if n.port_id == port]

    async def get_system_info(self) -> SystemInfo:
        """Protocols + mgmt services (NETCONF get-config) and the MAC table
        (SSH CLI — the xorplus NETCONF model doesn't expose forwarding state)."""
        protocols: tuple[ProtocolStatus, ...] = ()
        services: tuple[MgmtService, ...] = ()
        try:
            cfg = await self._netconf.get_config(source="running")
            protocols = _parse_protocols_xml(cfg)
            services = _parse_services_xml(cfg)
        except Exception:
            pass

        mac_table: tuple[MacEntry, ...] = ()
        mac_supported = True
        try:
            out = await self._ssh.run('cli -c "show ethernet-switching table"')
            mac_table = _parse_mac_table(out)
        except Exception:
            mac_supported = False

        facts = DeviceFacts()
        try:
            ver = await self._ssh.run('cli -c "show version"')
            facts = _parse_show_version(ver)
        except Exception:
            pass

        return SystemInfo(
            protocols=protocols,
            services=services,
            mac_table=mac_table,
            mac_supported=mac_supported,
            facts=facts,
        )

    async def get_protocol_detail(self, slug: str) -> ProtocolDetail:
        """Run a protocol's operational ``show`` gets over SSH and parse each
        with its TextFSM template. ``slug`` is the System-tab protocol label."""
        gets = PROTOCOL_GETS.get(slug) or STANDALONE_GETS.get(slug)
        if not gets:
            return ProtocolDetail(slug=slug)
        tables: list[ProtocolTable] = []
        error: str | None = None
        for get in gets:
            try:
                out = await self._ssh.run(f'cli -c "{get.command}"')
                tables.append(parse_table(get.title, get.template, out))
            except Exception as exc:
                error = error if error else f"{get.command}: {exc}"
        return ProtocolDetail(slug=slug, tables=tuple(tables), error=error)

    async def get_vlans(self) -> list[VlanInfo]:
        """The device VLAN database from get-config, with per-VLAN member-port
        counts derived from the same config (interface switchport membership)."""
        try:
            cfg = await self._netconf.get_config(source="running")
        except Exception:
            return []
        ports = _parse_interfaces_xml(cfg)
        usage: dict[int, int] = {}
        for p in ports:
            for v in {p.untagged_vlan, *p.tagged_vlans}:
                if isinstance(v, int):
                    usage[v] = usage.get(v, 0) + 1
        return _parse_vlans_xml(cfg, usage)

    async def get_l3_interfaces(self) -> list[L3Interface]:
        """Management port, L3 VLAN SVIs, and aggregated-ethernet from config."""
        try:
            cfg = await self._netconf.get_config(source="running")
        except Exception:
            return []
        return _parse_l3_interfaces_xml(cfg)

    async def get_ospf_interfaces(self) -> list[OspfInterfaceInfo]:
        """OSPF-enabled interfaces (name/area/tuning) from the <ospf> config."""
        try:
            cfg = await self._netconf.get_config(source="running")
        except Exception:
            return []
        return _parse_ospf_interfaces_xml(cfg)

    # ---------- write ----------

    async def render_change(self, port: str, change: PortChange) -> ConfigDiff:
        token = f"pica8-{uuid.uuid4().hex[:8]}"
        main = _build_edit_config_xml(port, change)
        # Setting (non-empty) tagged VLANs on a trunk is a two-phase write: phase 1
        # clears the keyed <members> list, phase 2 installs the new set. Otherwise
        # a single payload suffices.
        commands: tuple[str, ...]
        if change.tagged_vlans and _effective_mode(change) == "trunk":
            commands = (_clear_vlan_xml(port), main)
        else:
            commands = (main,)
        return ConfigDiff(
            summary=f"Update {port}",
            raw_before=f"<!-- previous state for {port} not captured -->",
            raw_after="\n".join(commands),
            commands=commands,
            # Stash the port + intent so apply_change can read the config back and
            # verify the device actually applied it (see _verify_applied).
            metadata={_TOKEN_KEY: token, _PORT_KEY: port, _INTENT_KEY: change.model_dump_json()},
        )

    async def render_vlan_change(self, change: VlanChange) -> ConfigDiff:
        """Render a VLAN-database create/delete as a xorplus ``<vlans>`` edit.

        No ``_PORT_KEY`` in metadata, so apply_change's port-level readback verify
        is skipped — a clean commit IS the success signal for a VLAN-db write.
        """
        token = f"pica8-{uuid.uuid4().hex[:8]}"
        main = _build_vlan_edit_config_xml(change)
        verb = "Create" if change.action == "create" else "Delete"
        return ConfigDiff(
            summary=f"{verb} VLAN {change.vlan_id}",
            raw_before=f"<!-- vlan {change.vlan_id} prior state not captured -->",
            raw_after=main,
            commands=(main,),
            metadata={_TOKEN_KEY: token},
        )

    async def render_l3_change(self, change: L3Change) -> ConfigDiff:
        """Render an SVI (VLAN-interface) or loopback create/delete via NETCONF.

        Both map to `set l3-interface {vlan-interface|loopback} <name> ...`; an SVI
        also needs the VLAN l3-interface link (see :func:`_build_l3_edit_config_xml`)."""
        token = f"pica8-{uuid.uuid4().hex[:8]}"
        main = _build_l3_edit_config_xml(change)
        verb = "Create" if change.action == "create" else "Delete"
        label = "SVI" if change.kind == "svi" else "loopback"
        return ConfigDiff(
            summary=f"{verb} {label} {change.iface_name}",
            raw_before=f"<!-- {change.iface_name} prior state not captured -->",
            raw_after=main,
            commands=(main,),
            metadata={_TOKEN_KEY: token},
        )

    async def render_vrf_change(self, change: VrfChange) -> ConfigDiff:
        """Render a VRF create/delete via NETCONF (`set ip vrf <name>`)."""
        token = f"pica8-{uuid.uuid4().hex[:8]}"
        main = _build_vrf_edit_config_xml(change)
        verb = "Create" if change.action == "create" else "Delete"
        return ConfigDiff(
            summary=f"{verb} VRF {change.name}",
            raw_before=f"<!-- vrf {change.name} prior state not captured -->",
            raw_after=main,
            commands=(main,),
            metadata={_TOKEN_KEY: token},
        )

    async def render_ospf_change(self, change: OspfChange) -> ConfigDiff:
        """Render an OSPFv2 change via NETCONF (`set protocols ospf ...`)."""
        token = f"pica8-{uuid.uuid4().hex[:8]}"
        main = _build_ospf_edit_config_xml(change)
        what = "router-id" if change.target == "router-id" else f"interface {change.interface}"
        return ConfigDiff(
            summary=f"OSPF {change.action} {what}",
            raw_before="<!-- ospf prior state not captured -->",
            raw_after=main,
            commands=(main,),
            metadata={_TOKEN_KEY: token},
        )

    async def apply_change(
        self,
        diff: ConfigDiff,
        *,
        confirm_seconds: int = 60,
    ) -> ApplyResult:
        token = diff.metadata.get(_TOKEN_KEY)
        if not token or not diff.commands:
            return ApplyResult(
                success=False,
                confirm_token=None,
                confirm_deadline_at=None,
                error="ConfigDiff missing pending_token or commands",
            )
        # xorplus has no :confirmed-commit, so a commit is permanent immediately —
        # there is no revert window. A change may need >1 edit (a trunk tagged-VLAN
        # write is clear-then-set: phase 1 removes the keyed <members> list, phase 2
        # merges the new set into the now-empty list). ALL edits are staged into ONE
        # candidate and applied with a SINGLE commit, so the change is atomic: if the
        # commit fails we discard and running config is untouched — never left in the
        # mid-state where the clear committed but the set didn't (which would wipe a
        # trunk's tagged VLANs).
        try:
            confirmed = await self._netconf.supports(":confirmed-commit")
            # Clean candidate first: a prior apply that failed AFTER edit_config
            # leaves its edit staged; without this, retries stack <interface> blocks
            # → commit fails 'Duplicate key "interface:id"'. (discard only touches the
            # uncommitted candidate, never the committed running config.)
            with contextlib.suppress(Exception):
                await self._netconf.discard_changes()
            for xml_payload in diff.commands:
                # A targeted delete (clearing a leaf) needs default-operation="none":
                # only the operation-tagged node acts; under "merge" xorplus keeps the
                # existing leaf. remove/(plain merge) work under the default merge.
                default_op = "none" if 'operation="delete"' in xml_payload else None
                await self._netconf.edit_config(
                    target="candidate", config=xml_payload, default_operation=default_op
                )
            await self._netconf.commit(
                confirmed=confirmed,
                timeout=confirm_seconds if confirmed else None,
            )
        except Exception as exc:
            # Don't leave the rejected edit staged in the candidate — it would
            # collide with the next apply. Discard is best-effort.
            with contextlib.suppress(Exception):
                await self._netconf.discard_changes()
            return ApplyResult(
                success=False,
                confirm_token=None,
                confirm_deadline_at=None,
                error=_classify_netconf_error(exc),
            )

        # Read the config back and confirm the device actually applied the intent.
        # The commit can succeed while the change is only partially applied (e.g.
        # the intermittent trunk→access port-mode flip) — surface that as a failure
        # instead of a false success.
        intent_raw = diff.metadata.get(_INTENT_KEY)
        verify_port = diff.metadata.get(_PORT_KEY)
        if intent_raw and verify_port:
            try:
                cfg = await self._netconf.get_config(source="running")
                drift = _verify_applied(
                    cfg, verify_port, PortChange.model_validate_json(intent_raw)
                )
            except Exception as exc:  # readback failed — can't confirm, report it
                drift = f"post-write verification could not read config: {exc}"
            if drift:
                return ApplyResult(
                    success=False,
                    confirm_token=None,
                    confirm_deadline_at=None,
                    error=f"committed but not fully applied on device: {drift}",
                )

        if not confirmed:
            return ApplyResult(
                success=True,
                confirm_token=None,
                confirm_deadline_at=None,
                error=None,
            )
        self._pending_token = token
        return ApplyResult(
            success=True,
            confirm_token=token,
            confirm_deadline_at=time.time() + confirm_seconds,
            error=None,
        )

    async def confirm(self, apply_token: str) -> None:
        if self._pending_token != apply_token:
            raise DriverError(
                f"pica8 confirm: token mismatch (got {apply_token!r}, "
                f"pending {self._pending_token!r})"
            )
        await self._netconf.commit(confirmed=False)
        self._pending_token = None

    async def revert(self, apply_token: str) -> None:
        if self._pending_token != apply_token:
            raise DriverError(
                f"pica8 revert: token mismatch (got {apply_token!r}, "
                f"pending {self._pending_token!r})"
            )
        await self._netconf.discard_changes()
        self._pending_token = None


# ---------------------------------------------------------------------------
# XML parsers — private, pure, easy to unit-test
# ---------------------------------------------------------------------------


def _classify_netconf_error(exc: BaseException) -> str:
    """Map common ncclient error messages to canonical exception text."""
    msg = str(exc).lower()
    if "auth" in msg or "permission" in msg:
        return f"auth error: {exc}"
    if "connect" in msg or "timeout" in msg or "refused" in msg:
        return f"reachability error: {exc}"
    return str(exc)


def _speed_to_mbps(raw: str) -> int | None:
    """'40Gb/s'->40000, '10Gb/s'->10000, '1000'->1000, '100Mb/s'->100, 'Auto'->None."""
    s = raw.strip().lower().replace("b/s", "").replace("bps", "")
    if not s or s in ("auto", "unknown", "n/a", "-"):
        return None
    try:
        if s.endswith("g"):
            return int(float(s[:-1]) * 1000)
        if s.endswith("m"):
            return int(float(s[:-1]))
        return int(float(s))
    except ValueError:
        return None


def _parse_interface_oper(text: str) -> dict[str, dict[str, object]]:
    """Parse `show interface` operational blocks -> {iface: {link_up, speed_mbps,
    duplex, mac, mtu}} via TextFSM (templates/pica8/show_interface.textfsm)."""
    from northbound.drivers._protocol_gets import parse_table

    table = parse_table("interfaces", "show_interface.textfsm", text)
    cols = {c: i for i, c in enumerate(table.columns)}
    out: dict[str, dict[str, object]] = {}
    for row in table.rows:
        name = row[cols["Name"]]
        duplex = row[cols["Duplex"]].strip().lower()
        mtu_raw = row[cols["Mtu"]]
        out[name] = {
            "link_up": row[cols["Link"]] == "Up",
            "speed_mbps": _speed_to_mbps(row[cols["Speed"]]),
            "duplex": duplex if duplex in ("full", "half") else None,
            "mac": (row[cols["Mac"]] or "").lower() or None,
            "mtu": int(mtu_raw) if mtu_raw.isdigit() else None,
        }
    return out


def _merge_oper(port: PortState, oper: dict[str, object] | None) -> PortState:
    """Overlay operational fields (speed/duplex/mac/link/mtu) onto a config-only
    PortState. Returns a new immutable PortState (no mutation)."""
    if not oper:
        return port
    from dataclasses import replace

    return replace(
        port,
        link_up=bool(oper.get("link_up", port.link_up)),
        speed_mbps=oper.get("speed_mbps") or port.speed_mbps,  # type: ignore[arg-type]
        duplex=oper.get("duplex") or port.duplex,  # type: ignore[arg-type]
        mac=oper.get("mac") or port.mac,  # type: ignore[arg-type]
        mtu=oper.get("mtu") or port.mtu,  # type: ignore[arg-type]
    )


def _parse_show_version(text: str) -> DeviceFacts:
    """Parse PicOS ``show version`` (``Key : Value`` lines) into DeviceFacts.

    Some PicOS builds merge the Hardware ID + Device MAC lines, so the base MAC
    is extracted by pattern over the whole text rather than a clean key.
    """
    kv: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            kv[k.strip().lower()] = v.strip()
    mac = ""
    m = re.search(r"Device MAC Address\s*:\s*([0-9A-Fa-f:]{17})", text)
    if m:
        mac = m.group(1).lower()
    return DeviceFacts(
        model=kv.get("model", ""),
        os_version=kv.get("software version", ""),
        serial=kv.get("serial number", ""),
        uptime=kv.get("system uptime", ""),
        license=kv.get("license type", ""),
        base_mac=mac,
        released=kv.get("software released date", ""),
    )


def _localname(tag: object) -> str:
    """Strip the ``{namespace}`` prefix from an etree tag."""
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _safe_parse(xml: str) -> etree._Element | None:
    """Parse XML, returning ``None`` on any failure.

    Permissive on purpose — vendor responses include leading whitespace,
    rpc-reply envelopes, etc. We want the parsers to be forgiving.
    """
    if not xml or not isinstance(xml, str):
        return None
    try:
        # recover=True so a trailing newline or stray ns doesn't kill parse
        parser = etree.XMLParser(recover=True, resolve_entities=False)
        return etree.fromstring(xml.encode("utf-8"), parser=parser)
    except etree.XMLSyntaxError:
        return None


def _find_first(root: etree._Element, name: str) -> etree._Element | None:
    """Find the first descendant element with the given local name."""
    for el in root.iter():
        if _localname(el.tag) == name:
            return el
    return None


def _find_all(root: etree._Element, name: str) -> list[etree._Element]:
    return [el for el in root.iter() if _localname(el.tag) == name]


def _child_text(el: etree._Element, name: str) -> str | None:
    """First-level child by local name, return stripped text or None."""
    for child in el:
        if _localname(child.tag) == name and child.text is not None:
            return child.text.strip()
    return None


def _has_child(el: etree._Element, name: str) -> bool:
    """True if a first-level child element by local name exists.

    Used for boolean tags like ``<disable/>`` where presence — not text
    content — is the signal. ``_child_text`` can't distinguish missing from
    empty self-closing.
    """
    return any(_localname(child.tag) == name for child in el)


# Physical-port element local-names in the real PicOS xorplus interface model
# (``http://pica8.com/xorplus/interface``). Each is a sibling list entry under
# ``<interface>``, NOT a Junos ``<interface><name>`` node — verified live on
# PicOS-V 4.2.2, where ports are ``<gigabit-ethernet><name>te-1/1/1</name>...``.
# (The earlier Junos-xnm assumption was a fabricated-fixture bug.)
_PORT_ELEMENTS = frozenset(
    {
        "gigabit-ethernet",
        "ten-gigabit-ethernet",
        "twentyfive-gigabit-ethernet",
        "forty-gigabit-ethernet",
        "hundred-gigabit-ethernet",
        "fortygig-ethernet",
        "hundredgig-ethernet",
        # Aggregated-ethernet bundles (LAGs) are switchport-like — include them
        # so they show with their VLAN membership. (management-ethernet is
        # IP-based, not a switchport; surfaced via device mgmt_ip, not here.)
        "aggregated-ethernet",
    }
)


def _parse_interfaces_xml(xml: str) -> list[PortState]:
    """Build PortState list from a NETCONF get-config running response.

    Ports are ``<gigabit-ethernet>`` (and higher-speed) list entries under the
    ``<interface xmlns="http://pica8.com/xorplus/interface">`` container — the
    real PicOS xorplus model. Each carries ``<name>``, ``<description>``,
    ``<mtu>``, ``<disable>``. VLAN membership lives in a separate model and is
    overlaid by ``_parse_vlan_membership`` where present.
    """
    root = _safe_parse(xml)
    if root is None:
        return []
    out: list[PortState] = []
    port_els = [el for el in root.iter() if _localname(el.tag) in _PORT_ELEMENTS]
    for iface_el in port_els:
        name = _child_text(iface_el, "name")
        if not name:
            continue
        # PicOS xorplus uses a boolean-VALUE leaf ``<disable>false</disable>``
        # (verified live), NOT a presence flag — so read the text: admin-down
        # only when it explicitly says "true". Absent ⇒ admin-up.
        disable_text = (_child_text(iface_el, "disable") or "").strip().lower()
        admin_up = disable_text != "true"
        description = _child_text(iface_el, "description") or ""
        mtu_text = _child_text(iface_el, "mtu")
        mtu: int | None = None
        if mtu_text and mtu_text.isdigit():
            mtu = int(mtu_text)
        untagged, tagged = _parse_vlan_membership(iface_el)
        out.append(
            PortState(
                name=name,
                admin_up=admin_up,
                link_up=admin_up,  # config-only view; oper state needs <get>
                speed_mbps=None,
                duplex=None,
                mac=None,
                mtu=mtu,
                untagged_vlan=untagged,
                tagged_vlans=tagged,
                description=description,
                host_model="",
                bmc_ip="",
                notes="",
                services={},
            )
        )
    return _collapse_logical_units(out)


def _collapse_logical_units(ports: list[PortState]) -> list[PortState]:
    """Drop Junos/xorplus logical sub-units (``xe-1/1/1.4``) when their parent
    physical interface (``xe-1/1/1``) is also present.

    PicOS reports both the physical port and its logical units; for a
    switchport view the physical port is the managed entity (it carries the
    access/trunk VLAN + description). A unit whose parent is absent is kept, so
    no data is silently lost on configs that only define units.
    """
    physical = {p.name for p in ports if "." not in p.name}
    return [p for p in ports if p.name.rpartition(".")[0] not in physical]


def _parse_vlans_xml(xml: str, usage: dict[int, int]) -> list[VlanInfo]:
    """Parse the xorplus ``<vlans>`` database: each ``<vlan-id>`` carries an
    ``<id>``, ``<vlan-name>``, optional ``<description>`` and ``<l3-interface>``
    (SVI). ``usage`` maps vlan-id -> member-port count (from interfaces)."""
    root = _safe_parse(xml)
    if root is None:
        return []
    out: list[VlanInfo] = []
    for el in root.iter():
        if _localname(el.tag) != "vlan-id":
            continue
        id_text = _child_text(el, "id")
        if not id_text or not id_text.strip().isdigit():
            continue
        vid = int(id_text.strip())
        out.append(
            VlanInfo(
                vlan_id=vid,
                name=_child_text(el, "vlan-name") or "",
                description=_child_text(el, "description") or "",
                l3_interface=_child_text(el, "l3-interface") or "",
                port_count=usage.get(vid, 0),
            )
        )
    out.sort(key=lambda v: v.vlan_id)
    return out


def _parse_l3_interfaces_xml(xml: str) -> list[L3Interface]:
    """Addressed interfaces from config: management-ethernet (eth0 + gateway),
    l3-interface vlan SVIs (ip/prefix/mtu), and aggregated-ethernet (LAGs)."""
    root = _safe_parse(xml)
    if root is None:
        return []
    out: list[L3Interface] = []

    # Management port: <management-ethernet><name>eth0</name>
    #   <ip-address><IPv4>192.168.85.202/24</IPv4></ip-address>
    #   <ip-gateway><IPv4>192.168.85.10</IPv4></ip-gateway>
    mgmt = _find_first(root, "management-ethernet")
    if mgmt is not None:
        ip_el = _find_first(mgmt, "ip-address")
        gw_el = _find_first(mgmt, "ip-gateway")
        out.append(
            L3Interface(
                name=_child_text(mgmt, "name") or "eth0",
                kind="management",
                ipv4=(_child_text(ip_el, "IPv4") or "") if ip_el is not None else "",
                gateway=(_child_text(gw_el, "IPv4") or "") if gw_el is not None else "",
            )
        )

    # SVIs: <l3-interface><vlan-interface><name>vlan1010</name>
    #   <address><ip>10.10.250.2</ip><prefix-length>16</prefix-length></address>
    for vi in root.iter():
        if _localname(vi.tag) != "vlan-interface":
            continue
        addr = _find_first(vi, "address")
        ip = _child_text(addr, "ip") if addr is not None else None
        prefix = _child_text(addr, "prefix-length") if addr is not None else None
        ipv4 = f"{ip}/{prefix}" if ip and prefix else (ip or "")
        mtu_text = _child_text(vi, "mtu")
        out.append(
            L3Interface(
                name=_child_text(vi, "name") or "",
                kind="svi",
                ipv4=ipv4,
                mtu=int(mtu_text) if mtu_text and mtu_text.isdigit() else None,
                enabled=(_child_text(vi, "disable") or "").strip().lower() != "true",
            )
        )

    # Loopbacks: <l3-interface><loopback><name>lo0</name>
    #   <address><ip>10.0.0.1</ip><prefix-length>32</prefix-length></address>
    # The interface <loopback> always has a <name>; the per-port
    # <loopback>false</loopback> boolean (loopback-detection) has none — skip those.
    for lb in root.iter():
        if _localname(lb.tag) != "loopback":
            continue
        name = _child_text(lb, "name")
        if not name:
            continue
        addr = _find_first(lb, "address")
        ip = _child_text(addr, "ip") if addr is not None else None
        prefix = _child_text(addr, "prefix-length") if addr is not None else None
        ipv4 = f"{ip}/{prefix}" if ip and prefix else (ip or "")
        mtu_text = _child_text(lb, "mtu")
        out.append(
            L3Interface(
                name=name,
                kind="loopback",
                ipv4=ipv4,
                mtu=int(mtu_text) if mtu_text and mtu_text.isdigit() else None,
                enabled=(_child_text(lb, "disable") or "").strip().lower() != "true",
            )
        )

    # LAGs: <aggregated-ethernet><name>ae0</name>... (members best-effort)
    for ae in root.iter():
        if _localname(ae.tag) != "aggregated-ethernet":
            continue
        members = [_child_text(m, "name") or "" for m in ae.iter() if _localname(m.tag) == "member"]
        out.append(
            L3Interface(
                name=_child_text(ae, "name") or "",
                kind="aggregated",
                detail=", ".join(m for m in members if m),
            )
        )
    return out


def _has_ancestor(el: etree._Element, ancestor_localname: str) -> bool:
    parent = el.getparent()
    while parent is not None:
        if _localname(parent.tag) == ancestor_localname:
            return True
        parent = parent.getparent()
    return False


def _expand_vlan_range(spec: str) -> list[int]:
    """Expand a xorplus member spec like '1000-1004,1010,1050-1064' -> [int...]."""
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, _, hi = part.partition("-")
            if lo.strip().isdigit() and hi.strip().isdigit():
                out.extend(range(int(lo), int(hi) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


def _parse_vlan_membership(iface_el: etree._Element) -> tuple[int | None, tuple[int, ...]]:
    """Pull access / trunk VLANs from a Pica8 interface block.

    Real xorplus structure (the NETCONF way):
        <family><ethernet-switching>
          <native-vlan-id>1065</native-vlan-id>
          <port-mode>trunk</port-mode>
          <vlan><members><id>1000-1004,1010,1050-1064</id></members></vlan>
    The member list is a comma/range string inside an ``<id>`` child of
    ``<members>`` (older configs put it directly as ``<members>`` text).
    """
    port_mode_el = next((el for el in iface_el.iter() if _localname(el.tag) == "port-mode"), None)
    mode = (port_mode_el.text or "").strip().lower() if port_mode_el is not None else ""

    members: list[int] = []
    for member_el in iface_el.iter():
        if _localname(member_el.tag) != "members":
            continue
        # spec is the <members> text, or an <id> child's text
        spec = (member_el.text or "").strip()
        if not spec:
            id_child = next(
                (c for c in member_el.iter() if _localname(c.tag) == "id" and c is not member_el),
                None,
            )
            spec = (id_child.text or "").strip() if id_child is not None else ""
        members.extend(_expand_vlan_range(spec))

    native = None
    native_el = next((el for el in iface_el.iter() if _localname(el.tag) == "native-vlan-id"), None)
    if native_el is not None and (native_el.text or "").strip().isdigit():
        native = int(native_el.text.strip())

    if mode == "trunk":
        # native = untagged; tagged = members minus the native (it's carried untagged)
        tagged = tuple(v for v in members if v != native)
        return native, tagged
    # access port — the single member is the access VLAN
    return (members[0] if members else native), ()


def _effective_mode(change: PortChange) -> str | None:
    """The port-mode a change implies: explicit wins, else infer from VLANs.

    A NON-EMPTY tagged set ⇒ trunk; an empty/absent tagged with any VLAN field ⇒
    access. Shared by the builder, render_change, and the post-write verify so all
    three agree on what "this change means".
    """
    mode = change.port_mode
    if mode is None and (change.untagged_vlan is not None or change.tagged_vlans is not None):
        mode = "trunk" if change.tagged_vlans else "access"
    return mode


def _descendant_text(el: etree._Element, name: str) -> str | None:
    """First descendant by local name, stripped text, or None."""
    node = next((x for x in el.iter() if _localname(x.tag) == name), None)
    return (node.text or "").strip() if node is not None and node.text else None


def _iface_members(iface: etree._Element) -> set[int]:
    """All VLAN ids in the port's <members> entries (range-expanded)."""
    out: set[int] = set()
    for m in iface.iter():
        if _localname(m.tag) != "members":
            continue
        spec = (m.text or "").strip() or next(
            ((c.text or "").strip() for c in m.iter() if _localname(c.tag) == "id" and c is not m),
            "",
        )
        out.update(_expand_vlan_range(spec))
    return out


def _verify_scalars(iface: etree._Element, change: PortChange) -> list[str]:
    """Drift in description / mtu / enabled, if those fields were set."""
    out: list[str] = []
    if change.description is not None:
        got = _child_text(iface, "description") or ""
        if got != change.description:
            out.append(f"description={got!r}≠{change.description!r}")
    if change.mtu is not None and (_child_text(iface, "mtu") or "") != str(change.mtu):
        out.append(f"mtu={_child_text(iface, 'mtu')}≠{change.mtu}")
    if change.enabled is not None:
        got_enabled = (_child_text(iface, "disable") or "").lower() != "true"
        if got_enabled != change.enabled:
            out.append(f"enabled={got_enabled}≠{change.enabled}")
    return out


def _verify_vlans(iface: etree._Element, change: PortChange) -> list[str]:
    """Drift in port-mode / native VLAN / tagged members, if those were set."""
    out: list[str] = []
    mode = _effective_mode(change)
    got_mode = _descendant_text(iface, "port-mode")
    if mode is not None and got_mode is not None and got_mode.lower() != mode:
        out.append(f"port-mode={got_mode}≠{mode}")
    if change.untagged_vlan is not None:
        got_native = _descendant_text(iface, "native-vlan-id")
        if got_native != str(change.untagged_vlan):
            out.append(f"native-vlan={got_native}≠{change.untagged_vlan}")
    if change.tagged_vlans is not None:
        got = _iface_members(iface)
        if got != set(change.tagged_vlans):
            out.append(f"tagged={sorted(got)}≠{sorted(change.tagged_vlans)}")
    return out


def _verify_applied(cfg: str, port: str, change: PortChange) -> str | None:
    """Confirm the running config matches the intended change; None if it does.

    Guards against a commit the device accepted but did not fully apply (e.g. the
    intermittent trunk→access port-mode flip): each set field is read back and
    compared. Returns a human description of any drift so the caller surfaces a
    real failure instead of a false success.
    """
    iface = next(
        (
            el
            for el in etree.fromstring(cfg.encode()).iter()
            if _localname(el.tag) == "gigabit-ethernet" and (_child_text(el, "name") or "") == port
        ),
        None,
    )
    if iface is None:
        return f"{port} not present in running config after write"
    mismatches = _verify_scalars(iface, change) + _verify_vlans(iface, change)
    return "; ".join(mismatches) if mismatches else None


def _parse_lldp_xml(xml: str) -> list[Neighbor]:
    """Extract LLDP neighbors from a get-config / get response.

    Pica8 surfaces neighbors under ``<lldp><neighbor>`` blocks. Each block
    carries chassis-id, port-id, system-name, system-description, and the
    local interface name (``<interface-name>``).
    """
    root = _safe_parse(xml)
    if root is None:
        return []
    out: list[Neighbor] = []
    for neighbor_el in _find_all(root, "neighbor"):
        if not _has_ancestor(neighbor_el, "lldp"):
            continue
        chassis_id = _child_text(neighbor_el, "chassis-id") or ""
        remote_port = _child_text(neighbor_el, "port-id") or ""
        sys_name = _child_text(neighbor_el, "system-name")
        sys_desc = _child_text(neighbor_el, "system-description")
        local_port = _child_text(neighbor_el, "interface-name")
        # Stash the local port in ``port_id`` so ``get_neighbors(port=...)``
        # can filter on it. The remote port is implicit in chassis_id pairing
        # and the system_description prefix below.
        port_id_value = local_port or remote_port
        desc_prefix = f"[remote-port {remote_port}] " if remote_port else ""
        out.append(
            Neighbor(
                chassis_id=chassis_id,
                port_id=port_id_value,
                system_name=sys_name,
                system_description=(desc_prefix + (sys_desc or "")).strip() or None,
            )
        )
    return out


# Top-level xorplus config sections that represent control-plane protocols.
# (slug, label). ``bgp`` detection is by element presence — leaf-02 has no BGP,
# but a BGP-running leaf carries a bgp config element; operational detail then
# comes from the FRR ``show ip bgp summary`` get.
_PROTOCOL_SECTIONS: tuple[tuple[str, str], ...] = (
    ("lldp", "LLDP"),
    ("ospf", "OSPF"),
    ("bgp", "BGP"),
    ("spanning-tree", "Spanning Tree"),
    ("lacp", "LACP"),
    ("loopback-detection", "Loopback Detection"),
    ("dhcp", "DHCP"),
    ("firewall", "Firewall"),
)


def _section_enabled(el: etree._Element) -> bool:
    """True unless the section is an explicit boolean-false leaf or carries
    ``<enable>false</enable>``. A bare container (no enable child) ⇒ enabled."""
    txt = (el.text or "").strip().lower()
    if txt in ("false", "true"):  # boolean leaf like <dhcp>false</dhcp>
        return txt == "true"
    enable = _child_text(el, "enable")
    if enable is not None:
        return enable.strip().lower() == "true"
    return True


def _iter_local(el: etree._Element, name: str) -> list[etree._Element]:
    return [e for e in el.iter() if _localname(e.tag) == name]


def _detail_lldp(el: etree._Element) -> tuple[list[tuple[str, str]], str]:
    iv = _child_text(el, "advertisement-interval")
    n = len(_iter_local(el, "interface"))
    params = [("Interfaces", str(n))]
    if iv:
        params.insert(0, ("Advertisement interval", f"{iv}s"))
    return params, f"{n} interfaces" + (f" · {iv}s" if iv else "")


def _detail_ospf(el: etree._Element) -> tuple[list[tuple[str, str]], str]:
    rid = _child_text(el, "router-id")
    ifaces = _iter_local(el, "interface")
    areas = sorted({_child_text(i, "area") or "" for i in ifaces} - {""})
    params: list[tuple[str, str]] = []
    if rid:
        params.append(("Router ID", rid))
    params.append(("Interfaces", str(len(ifaces))))
    if areas:
        params.append(("Areas", ", ".join(areas)))
    return params, " · ".join(
        p for p in ((f"router-id {rid}" if rid else ""), f"{len(ifaces)} ifaces") if p
    )


def _detail_stp(el: etree._Element) -> tuple[list[tuple[str, str]], str]:
    fv = (_child_text(el, "force-version") or "").strip()
    mode = {"3": "RSTP/MSTP", "0": "STP"}.get(fv, fv)
    vlans = _iter_local(el, "vlan")
    params: list[tuple[str, str]] = []
    if mode:
        params.append(("Mode", mode))
    if vlans:
        params.append(("PVST VLANs", str(len(vlans))))
        prio = _child_text(vlans[0], "bridge-priority")
        if prio:
            params.append(("Bridge priority", prio))
    return params, mode + (f" · {len(vlans)} PVST vlans" if vlans else "")


def _detail_lacp(el: etree._Element) -> tuple[list[tuple[str, str]], str]:
    prio = _child_text(el, "priority")
    return ([("System priority", prio)], f"priority {prio}") if prio else ([], "")


def _detail_lbd(el: etree._Element) -> tuple[list[tuple[str, str]], str]:
    iv = _child_text(el, "message-interval")
    return ([("Message interval", f"{iv}s")], f"{iv}s interval") if iv else ([], "")


def _detail_firewall(el: etree._Element) -> tuple[list[tuple[str, str]], str]:
    filters = _iter_local(el, "filter")
    names = [n for n in (_child_text(f, "name") or "" for f in filters) if n]
    return [("Filters", ", ".join(names) or str(len(filters)))], f"{len(filters)} filter(s)"


def _detail_bgp(el: etree._Element) -> tuple[list[tuple[str, str]], str]:
    # Best-effort over common FRR/xorplus leaf names; reads only what's present
    # (no assumed structure). Live operational data comes from the summary get.
    local_as = _child_text(el, "local-as") or _child_text(el, "as") or _child_text(el, "as-number")
    rid = _child_text(el, "router-id")
    neighbors = _iter_local(el, "neighbor") or _iter_local(el, "peer")
    params: list[tuple[str, str]] = []
    if local_as:
        params.append(("Local AS", local_as))
    if rid:
        params.append(("Router ID", rid))
    if neighbors:
        params.append(("Configured peers", str(len(neighbors))))
    # Per-neighbor config: peer address (child or @name attr) → remote-AS. The
    # exact leaf names aren't device-confirmed, so probe the common variants and
    # show whatever is present (no crash when a field is absent).
    for n in neighbors:
        addr = (
            _child_text(n, "name")
            or _child_text(n, "address")
            or _child_text(n, "peer-address")
            or n.get("name")
            or ""
        )
        ras = _child_text(n, "remote-as") or _child_text(n, "peer-as") or _child_text(n, "as")
        if addr:
            params.append((f"Neighbor {addr}", f"remote-AS {ras}" if ras else "configured"))
    summary = " · ".join(
        p for p in ((f"AS {local_as}" if local_as else ""), f"{len(neighbors)} peers") if p
    )
    return params, summary


_PROTOCOL_DETAIL = {
    "lldp": _detail_lldp,
    "ospf": _detail_ospf,
    "bgp": _detail_bgp,
    "spanning-tree": _detail_stp,
    "lacp": _detail_lacp,
    "loopback-detection": _detail_lbd,
    "firewall": _detail_firewall,
}


def _protocol_params(slug: str, el: etree._Element) -> tuple[list[tuple[str, str]], str]:
    """Extract (key/value detail rows, one-line summary) for a protocol block."""
    fn = _PROTOCOL_DETAIL.get(slug)
    return fn(el) if fn else ([], "")


def _parse_protocols_xml(xml: str) -> tuple[ProtocolStatus, ...]:
    """Report configured control-plane protocols with their key parameters.

    A boolean-false leaf (``<dhcp>false</dhcp>``) or ``<enable>false</enable>``
    is reported as present-but-disabled, NOT as an enabled protocol.
    """
    root = _safe_parse(xml)
    if root is None:
        return ()
    out: list[ProtocolStatus] = []
    for slug, label in _PROTOCOL_SECTIONS:
        el = _find_first(root, slug)
        if el is None:
            continue
        enabled = _section_enabled(el)
        params, summary = _protocol_params(slug, el) if enabled else ([], "disabled")
        out.append(
            ProtocolStatus(
                name=label,
                enabled=enabled,
                detail=summary,
                params=tuple(params),
                has_detail=enabled and label in PROTOCOL_GETS,
            )
        )
    return tuple(out)


# Canonical mgmt services we always report, so absent ones surface greyed as
# "not configured" rather than silently missing. (name, default port).
_KNOWN_SERVICES: tuple[tuple[str, int | None], ...] = (
    ("SSH", 22),
    ("Web (HTTP)", 80),
    ("Web (HTTPS)", 443),
    ("NETCONF", 830),
)


def _service_disabled(el: etree._Element) -> bool:
    return (_child_text(el, "disable") or "").strip().lower() == "true"


def _service_port(el: etree._Element, default: int | None) -> int | None:
    txt = _child_text(el, "port")
    return int(txt) if txt and txt.isdigit() else default


def _parse_services_xml(xml: str) -> tuple[MgmtService, ...]:
    """Report the canonical mgmt service set (ssh / web http+https / netconf).

    Present-in-config services carry their real enabled state + port; absent
    ones come back ``configured=False`` so the UI can grey them as "not
    configured". ``<disable>true</disable>`` is the xorplus boolean leaf.
    NETCONF: we're talking to the device over it, so a successful read ⇒
    present + enabled even though it lives under <protocols>, not <services>.
    """
    root = _safe_parse(xml)
    services_el = _find_first(root, "services") if root is not None else None

    def _find_under(parent: etree._Element | None, name: str) -> etree._Element | None:
        return _find_first(parent, name) if parent is not None else None

    web_el = _find_under(services_el, "web")
    found: dict[str, MgmtService] = {}
    ssh_el = _find_under(services_el, "ssh")
    if ssh_el is not None:
        found["SSH"] = MgmtService(
            name="SSH", enabled=not _service_disabled(ssh_el), port=_service_port(ssh_el, 22)
        )
    if web_el is not None:
        web_on = not _service_disabled(web_el)
        for proto, port in (("http", 80), ("https", 443)):
            sub = _find_first(web_el, proto)
            if sub is not None:
                found[f"Web ({proto.upper()})"] = MgmtService(
                    name=f"Web ({proto.upper()})",
                    enabled=web_on and not _service_disabled(sub),
                    port=_service_port(sub, port),
                )
    # NETCONF: reachable (this XML came over it) ⇒ present + enabled.
    if root is not None:
        found["NETCONF"] = MgmtService(name="NETCONF", enabled=True, port=830)

    out: list[MgmtService] = []
    for name, default_port in _KNOWN_SERVICES:
        if name in found:
            out.append(found[name])
        else:
            out.append(MgmtService(name=name, enabled=False, port=default_port, configured=False))
    return tuple(out)


def _parse_mac_table(text: str) -> tuple[MacEntry, ...]:
    """Parse ``show ethernet-switching table`` rows.

    Columns: VLAN  MAC address  Type  Age  Interfaces  User. Header/banner and
    summary lines are skipped; a row must start with a VLAN id and carry a
    colon-separated MAC.
    """
    out: list[MacEntry] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        vlan_tok, mac_tok, type_tok, age_tok, iface_tok = parts[:5]
        if not vlan_tok.isdigit() or mac_tok.count(":") != 5:
            continue
        out.append(
            MacEntry(
                vlan=int(vlan_tok),
                mac=mac_tok.lower(),
                type=type_tok,
                age=age_tok,
                interface=iface_tok,
            )
        )
    return tuple(out)


# Real PicOS xorplus interface model (verified against live get-config on an
# N8560-32C): interfaces live under <interface xmlns="…/xorplus/interface"> as a
# <gigabit-ethernet> list with <name>/<description> and VLAN membership under
# <family><ethernet-switching> (native-vlan-id + port-mode + vlan/members/id).
# This is NOT the Junos <interfaces><interface><unit> tree — that produced
# "no device/data that could be affected" on edit-config.
_XORPLUS_IFACE_NS = "http://pica8.com/xorplus/interface"
_NC_BASE_NS = "urn:ietf:params:xml:ns:netconf:base:1.0"
_XORPLUS_VLANS_NS = "http://pica8.com/xorplus/vlans"
# Grounded against a live get-config: the <l3-interface> element (SVIs) lives in
# the vlan-interface namespace, NOT a "l3-interface" one.
_XORPLUS_VLAN_IFACE_NS = "http://pica8.com/xorplus/vlan-interface"
# Grounded from a live get-config: `set ip vrf <name>` lives under <ip> in the
# ip-routing namespace.
_XORPLUS_IP_ROUTING_NS = "http://pica8.com/xorplus/ip-routing"
_XORPLUS_OSPFV2_NS = "http://pica8.com/xorplus/ospfv2"


def _build_edit_config_xml(port: str, change: PortChange) -> str:
    """Render a Pica8 ``<config>`` edit payload matching the xorplus schema.

    Only emits elements for fields the caller set; edit-config merges, so absent
    fields are left untouched. Ports on the supported hardware are
    ``<gigabit-ethernet>`` entries.
    """
    cfg = etree.Element("config")
    # Default namespace on the interface subtree (children unprefixed), mirroring
    # how the device returns it in get-config.
    iface = etree.SubElement(cfg, "interface", nsmap={None: _XORPLUS_IFACE_NS})
    ge = etree.SubElement(iface, "gigabit-ethernet")
    etree.SubElement(ge, "name").text = port
    if change.description is not None:
        desc = etree.SubElement(ge, "description")
        if change.description == "":
            # xorplus ignores an empty <description/> (no-op). To CLEAR a
            # description, delete the node via the NETCONF operation attribute.
            desc.set(f"{{{_NC_BASE_NS}}}operation", "delete")
        else:
            desc.text = change.description
    if change.mtu is not None:
        etree.SubElement(ge, "mtu").text = str(change.mtu)
    if change.enabled is not None:
        # xorplus models admin-down as <disable>; enabled=True -> disable=false.
        etree.SubElement(ge, "disable").text = "false" if change.enabled else "true"
    _append_switching(ge, change)
    return etree.tostring(cfg, pretty_print=True).decode("utf-8")


def _build_vlan_edit_config_xml(change: VlanChange) -> str:
    """Render a xorplus ``<vlans>`` edit for a VLAN-database create/delete.

    Schema (verified against a live get-config):
        <vlans xmlns="http://pica8.com/xorplus/vlans">
          <vlan-id><id>1010</id><vlan-name>web</vlan-name></vlan-id>
        </vlans>
    ``<id>`` is the list key. Create merges the entry; delete tags the keyed
    node with NETCONF operation="delete" (apply_change runs it under
    default-operation="none" so only the tagged node acts).
    """
    cfg = etree.Element("config")
    vlans = etree.SubElement(cfg, "vlans", nsmap={None: _XORPLUS_VLANS_NS})
    vlan_id = etree.SubElement(vlans, "vlan-id")
    etree.SubElement(vlan_id, "id").text = str(change.vlan_id)
    if change.action == "delete":
        vlan_id.set(f"{{{_NC_BASE_NS}}}operation", "delete")
    else:  # create — xorplus requires a name; default it to the id when unset
        etree.SubElement(vlan_id, "vlan-name").text = change.name or str(change.vlan_id)
        if change.description:
            etree.SubElement(vlan_id, "description").text = change.description
    return etree.tostring(cfg, pretty_print=True).decode("utf-8")


def _build_l3_edit_config_xml(change: L3Change) -> str:
    """Render a xorplus SVI create/delete (grounded against a live get-config).

    An SVI's interface object is *created by* the VLAN's ``<l3-interface>`` link;
    setting only the address fails with "Vlan-interface vlanN not found". So a
    create emits BOTH, in one edit-config:
        <vlans xmlns=".../vlans">
          <vlan-id><id>3997</id><l3-interface>vlan3997</l3-interface></vlan-id>
        </vlans>
        <l3-interface xmlns=".../vlan-interface">
          <vlan-interface><name>vlan3997</name>
            <address><ip>..</ip><prefix-length>..</prefix-length></address>
            [<mtu>..</mtu>][<disable>..</disable>][<dhcp>..</dhcp>]
          </vlan-interface>
        </l3-interface>
    Delete removes the address object AND the VLAN link (both operation="delete",
    run under default-operation="none"). Loopback is rejected upstream.
    """
    cfg = etree.Element("config")
    name = change.iface_name  # "vlan<id>" (svi) or the loopback name

    # An SVI's interface object is instantiated by the VLAN's l3-interface link;
    # a loopback is standalone (no VLAN). Emit the link only for SVIs.
    if change.kind == "svi":
        vlans = etree.SubElement(cfg, "vlans", nsmap={None: _XORPLUS_VLANS_NS})
        vlan_id = etree.SubElement(vlans, "vlan-id")
        etree.SubElement(vlan_id, "id").text = str(change.vlan_id)
        link = etree.SubElement(vlan_id, "l3-interface")
        link.text = name
        if change.action == "delete":
            link.set(f"{{{_NC_BASE_NS}}}operation", "delete")

    # The addressed interface: <vlan-interface> (SVI) or <loopback>, both under
    # <l3-interface> (CLI `set l3-interface {vlan-interface|loopback} <name> ...`).
    l3 = etree.SubElement(cfg, "l3-interface", nsmap={None: _XORPLUS_VLAN_IFACE_NS})
    child = "vlan-interface" if change.kind == "svi" else "loopback"
    iface = etree.SubElement(l3, child)
    etree.SubElement(iface, "name").text = name
    if change.action == "delete":
        iface.set(f"{{{_NC_BASE_NS}}}operation", "delete")
    else:
        ip, _, prefix = (change.ipv4 or "").partition("/")
        addr = etree.SubElement(iface, "address")
        etree.SubElement(addr, "ip").text = ip
        etree.SubElement(addr, "prefix-length").text = prefix
        if change.vrf:
            # `set l3-interface {vlan-interface|loopback} <name> vrf <name>`. The VRF
            # must already exist on the device; binding to an absent VRF is rejected.
            etree.SubElement(iface, "vrf").text = change.vrf
        if change.mtu is not None:
            etree.SubElement(iface, "mtu").text = str(change.mtu)
        if change.enabled is not None:
            etree.SubElement(iface, "disable").text = "false" if change.enabled else "true"
        if change.dhcp is not None:
            etree.SubElement(iface, "dhcp").text = "true" if change.dhcp else "false"
    return etree.tostring(cfg, pretty_print=True).decode("utf-8")


def _build_vrf_edit_config_xml(change: VrfChange) -> str:
    """Render a VRF create/delete (`set ip vrf <name> [description]`).

    Namespace grounded from a live get-config (<ip xmlns=.../ip-routing>); the
    ip>vrf>name path is from the PicOS CLI. ``<name>`` is the list key. Create
    merges name+description; delete tags the keyed <vrf> with operation="delete".
    """
    cfg = etree.Element("config")
    ip = etree.SubElement(cfg, "ip", nsmap={None: _XORPLUS_IP_ROUTING_NS})
    vrf = etree.SubElement(ip, "vrf")
    etree.SubElement(vrf, "name").text = change.name
    if change.action == "delete":
        vrf.set(f"{{{_NC_BASE_NS}}}operation", "delete")
    elif change.description:
        etree.SubElement(vrf, "description").text = change.description
    return etree.tostring(cfg, pretty_print=True).decode("utf-8")


def _parse_ospf_interfaces_xml(xml: str) -> list[OspfInterfaceInfo]:
    """Parse OSPF-enabled interfaces from the xorplus ``<ospf>`` config:
    ``<ospf><interface><name>vlanN</name><area>0.0.0.0</area>[<cost>][<hello-interval>]
    [<dead-interval>][<passive>]``."""
    root = _safe_parse(xml)
    if root is None:
        return []
    ospf = _find_first(root, "ospf")
    if ospf is None:
        return []
    out: list[OspfInterfaceInfo] = []
    for el in ospf.iter():
        if _localname(el.tag) != "interface":
            continue
        name = _child_text(el, "name")
        if not name:
            continue
        cost = _child_text(el, "cost")
        hello = _child_text(el, "hello-interval")
        dead = _child_text(el, "dead-interval")
        out.append(
            OspfInterfaceInfo(
                name=name,
                area=_child_text(el, "area") or "",
                cost=int(cost) if cost and cost.isdigit() else None,
                hello_interval=int(hello) if hello and hello.isdigit() else None,
                dead_interval=int(dead) if dead and dead.isdigit() else None,
                passive=(_child_text(el, "passive") or "").strip().lower() == "true",
            )
        )
    return out


def _build_ospf_edit_config_xml(change: OspfChange) -> str:
    """Render an OSPFv2 change under the xorplus ``<ospf>`` tree.

    Namespace + core structure grounded from a live get-config:
        <ospf xmlns="http://pica8.com/xorplus/ospfv2">
          <router-id>1.2.3.4</router-id>
          <interface><name>vlan1010</name><area>0.0.0.0</area>
            [<cost>][<hello-interval>][<dead-interval>][<passive>]</interface>
        </ospf>
    Interface name is the list key. delete tags the keyed node operation="delete".
    """
    cfg = etree.Element("config")
    ospf = etree.SubElement(cfg, "ospf", nsmap={None: _XORPLUS_OSPFV2_NS})
    if change.target == "router-id":
        rid = etree.SubElement(ospf, "router-id")
        if change.action == "delete":
            rid.set(f"{{{_NC_BASE_NS}}}operation", "delete")
        else:
            rid.text = change.router_id
    else:  # interface
        iface = etree.SubElement(ospf, "interface")
        etree.SubElement(iface, "name").text = change.interface
        if change.action == "delete":
            iface.set(f"{{{_NC_BASE_NS}}}operation", "delete")
        else:
            etree.SubElement(iface, "area").text = change.area
            if change.cost is not None:
                etree.SubElement(iface, "cost").text = str(change.cost)
            if change.hello_interval is not None:
                etree.SubElement(iface, "hello-interval").text = str(change.hello_interval)
            if change.dead_interval is not None:
                etree.SubElement(iface, "dead-interval").text = str(change.dead_interval)
            if change.passive is not None:
                etree.SubElement(iface, "passive").text = "true" if change.passive else "false"
    return etree.tostring(cfg, pretty_print=True).decode("utf-8")


def _clear_vlan_xml(port: str) -> str:
    """Phase-1 payload: remove a port's whole ``<vlan>`` subtree (clears members).

    Run before a trunk tagged-VLAN set so the keyed <members> list starts empty
    and the phase-2 merge can't collide ('Duplicate key "interface:id"').
    """
    cfg = etree.Element("config")
    iface = etree.SubElement(cfg, "interface", nsmap={None: _XORPLUS_IFACE_NS})
    ge = etree.SubElement(iface, "gigabit-ethernet")
    etree.SubElement(ge, "name").text = port
    eth = etree.SubElement(etree.SubElement(ge, "family"), "ethernet-switching")
    etree.SubElement(eth, "vlan").set(f"{{{_NC_BASE_NS}}}operation", "remove")
    return etree.tostring(cfg, pretty_print=True).decode("utf-8")


def _append_switching(ge: etree._Element, change: PortChange) -> None:
    """Append ``<family><ethernet-switching>`` (port-mode + VLANs) when relevant.

    Effective port-mode: an explicit ``change.port_mode`` wins; otherwise it is
    inferred from the VLAN fields (non-empty tagged ⇒ trunk, else access) so
    request-flow callers (which only set untagged/tagged) keep working.
    """
    mode = _effective_mode(change)
    if mode is None:
        return
    family = etree.SubElement(ge, "family")
    eth = etree.SubElement(family, "ethernet-switching")
    etree.SubElement(eth, "port-mode").text = mode
    if mode == "trunk":
        if change.untagged_vlan is not None:
            etree.SubElement(eth, "native-vlan-id").text = str(change.untagged_vlan)
        if change.tagged_vlans is not None:
            # <members> is a list keyed by <id>: a plain merge APPENDS a new entry,
            # so merging a changed set stacks duplicates and the commit fails with
            # 'Duplicate key "interface:id"'. A tagged write is therefore applied in
            # TWO phases (see render_change): phase 1 removes the whole <vlan>
            # subtree, phase 2 (this payload) merges the new members into the now-
            # empty list → one clean <members> entry. Empty list ⇒ just remove.
            vlan = etree.SubElement(eth, "vlan")
            if change.tagged_vlans:
                members = etree.SubElement(vlan, "members")
                etree.SubElement(members, "id").text = ",".join(str(v) for v in change.tagged_vlans)
            else:
                vlan.set(f"{{{_NC_BASE_NS}}}operation", "remove")
    else:  # access
        # xorplus access ports carry their VLAN in <native-vlan-id>, NOT
        # <vlan><members> — the device rejects members in access mode
        # ("can't include any vlan member at the access mode").
        if change.untagged_vlan is not None:
            etree.SubElement(eth, "native-vlan-id").text = str(change.untagged_vlan)
        # Switching trunk -> access leaves the old <vlan><members> behind (merge
        # never deletes); remove it so the port is a clean access port. "remove"
        # is idempotent — no error when there is nothing to delete.
        vlan = etree.SubElement(eth, "vlan")
        vlan.set(f"{{{_NC_BASE_NS}}}operation", "remove")
