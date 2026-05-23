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
"""

from __future__ import annotations

import time
import uuid

from lxml import etree  # type: ignore[attr-defined]  # lxml has no stubs; etree is C-extension

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
    Neighbor,
    PortChange,
    PortState,
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
        supports_snmp_read=True,
        supports_lldp=True,
        max_concurrency=1,
        auth_methods=[AuthMethod.PASSWORD, AuthMethod.SSH_KEY],
        web_ui_url_template="https://{mgmt_ip}:8888/",
    )

    def __init__(
        self,
        conn: ConnectionParams,
        creds: Credentials,
        *,
        netconf: NetconfClient | None = None,
    ) -> None:
        super().__init__(conn, creds)
        self._netconf = netconf if netconf is not None else self._build_netconf()
        # Token currently 'live' on the device — set by apply_change.
        self._pending_token: str | None = None

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


def _parse_interfaces_xml(xml: str) -> list[PortState]:
    """Build PortState list from a NETCONF get-config running response.

    Looks for ``<interface>`` blocks under any ``<interfaces>`` container.
    Each interface yields one PortState. VLAN membership comes from
    ``<unit>/<family>/<ethernet-switching>`` (Pica8 / Junos-style YANG).
    """
    root = _safe_parse(xml)
    if root is None:
        return []
    out: list[PortState] = []
    for iface_el in _find_all(root, "interface"):
        # The schema also has <interface> nodes inside <lldp/>; skip those —
        # they're under a <lldp> ancestor and don't carry full port state.
        if _has_ancestor(iface_el, "lldp"):
            continue
        name = _child_text(iface_el, "name")
        if not name:
            continue
        # <disable/> is a boolean tag — presence (even empty/self-closing)
        # means admin-down. _child_text can't see it; use _has_child.
        admin_up = not _has_child(iface_el, "disable")
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
    return out


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
