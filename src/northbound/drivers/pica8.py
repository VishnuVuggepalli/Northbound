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

import time
import uuid

from lxml import etree  # type: ignore[attr-defined]  # lxml has no stubs; etree is C-extension

from northbound._lib.transport.asyncssh_client import SshClient, SshParams
from northbound._lib.transport.netconf_client import NetconfClient, NetconfParams
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
    DiscoveryResult,
    DriverCapabilities,
    MacEntry,
    MgmtService,
    Neighbor,
    PortChange,
    PortState,
    ProtocolStatus,
    SystemInfo,
    TestResult,
)

# ConfigDiff metadata keys (kept here to avoid magic strings).
_TOKEN_KEY = "pending_token"


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
        return _parse_interfaces_xml(cfg)

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

        return SystemInfo(
            protocols=protocols,
            services=services,
            mac_table=mac_table,
            mac_supported=mac_supported,
        )

    # ---------- write ----------

    async def render_change(self, port: str, change: PortChange) -> ConfigDiff:
        token = f"pica8-{uuid.uuid4().hex[:8]}"
        xml_payload = _build_edit_config_xml(port, change)
        return ConfigDiff(
            summary=f"Update {port}",
            raw_before=f"<!-- previous state for {port} not captured -->",
            raw_after=xml_payload,
            commands=(xml_payload,),
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
        xml_payload = diff.commands[0]
        try:
            await self._netconf.edit_config(target="candidate", config=xml_payload)
            await self._netconf.commit(confirmed=True, timeout=confirm_seconds)
        except Exception as exc:
            return ApplyResult(
                success=False,
                confirm_token=None,
                confirm_deadline_at=None,
                error=_classify_netconf_error(exc),
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


def _has_ancestor(el: etree._Element, ancestor_localname: str) -> bool:
    parent = el.getparent()
    while parent is not None:
        if _localname(parent.tag) == ancestor_localname:
            return True
        parent = parent.getparent()
    return False


def _parse_vlan_membership(iface_el: etree._Element) -> tuple[int | None, tuple[int, ...]]:
    """Pull access / trunk vlans from a Pica8 interface block."""
    untagged: int | None = None
    tagged: list[int] = []
    # Pica8 / Junos-style: <unit><family><ethernet-switching><vlan><members>X
    # The 'port-mode' child is "access" or "trunk".
    port_mode_el = None
    for el in iface_el.iter():
        if _localname(el.tag) == "port-mode":
            port_mode_el = el
            break
    mode = (
        port_mode_el.text.strip().lower() if port_mode_el is not None and port_mode_el.text else ""
    )
    members: list[int] = []
    for member_el in iface_el.iter():
        if _localname(member_el.tag) != "members":
            continue
        if member_el.text and member_el.text.strip().isdigit():
            members.append(int(member_el.text.strip()))
    native = None
    for native_el in iface_el.iter():
        if _localname(native_el.tag) == "native-vlan-id":
            if native_el.text and native_el.text.strip().isdigit():
                native = int(native_el.text.strip())
            break
    if mode == "trunk":
        untagged = native
        tagged = members
    else:
        # access port — first member is the access vlan
        untagged = members[0] if members else native
        tagged = []
    return untagged, tuple(tagged)


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
_PROTOCOL_SECTIONS: tuple[tuple[str, str], ...] = (
    ("lldp", "LLDP"),
    ("ospf", "OSPF"),
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


_PROTOCOL_DETAIL = {
    "lldp": _detail_lldp,
    "ospf": _detail_ospf,
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
            ProtocolStatus(name=label, enabled=enabled, detail=summary, params=tuple(params))
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


def _build_edit_config_xml(port: str, change: PortChange) -> str:
    """Render a Pica8 ``<config>`` payload for an interface change.

    Keeps the XML small — only emit elements for fields the caller set.
    Pica8's edit-config merges by default, so absent fields are left
    untouched on the device.
    """
    # Use namespace-less XML — Pica8 accepts the family-style tree under
    # the device's default ns, and ncclient wraps with the proper rpc
    # envelope. Producing namespace-explicit XML here ties us to one
    # firmware revision.
    cfg = etree.Element("config")
    interfaces = etree.SubElement(cfg, "interfaces")
    iface = etree.SubElement(interfaces, "interface")
    etree.SubElement(iface, "name").text = port
    if change.description is not None:
        etree.SubElement(iface, "description").text = change.description
    if change.untagged_vlan is not None or change.tagged_vlans is not None:
        unit = etree.SubElement(iface, "unit")
        etree.SubElement(unit, "name").text = "0"
        family = etree.SubElement(unit, "family")
        eth = etree.SubElement(family, "ethernet-switching")
        if change.tagged_vlans is not None:
            etree.SubElement(eth, "port-mode").text = "trunk"
            if change.untagged_vlan is not None:
                etree.SubElement(eth, "native-vlan-id").text = str(change.untagged_vlan)
            vlan = etree.SubElement(eth, "vlan")
            for v in change.tagged_vlans:
                etree.SubElement(vlan, "members").text = str(v)
        elif change.untagged_vlan is not None:
            etree.SubElement(eth, "port-mode").text = "access"
            vlan = etree.SubElement(eth, "vlan")
            etree.SubElement(vlan, "members").text = str(change.untagged_vlan)
    return etree.tostring(cfg, pretty_print=True).decode("utf-8")
