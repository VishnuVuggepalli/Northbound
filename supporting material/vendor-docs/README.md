# Northbound — Vendor Reference

Canonical per-platform connection + config notes. Source of truth for driver implementation.

## Platform inventory

| Platform | Role | Writable? | Connection method |
|---|---|---|---|
| MikroTik **RouterOS** v7+ | leaf/spine | yes | REST (primary) + SSH (fallback) |
| MikroTik **SwOS** | leaf | **read-only forever** | SNMP read + HTTP scrape (backup blob only) |
| Arista EOS | leaf/spine | yes | eAPI (JSON-RPC over HTTPS) |
| Pica8 PicOS | leaf/spine | yes | NETCONF (port 830) + SSH CLI |
| FreeBSD | router / VPN | **read-only forever** | SSH only |

## ⚠️ SwOS vs RouterOS — architectural fork

The plan.md spec assumed all MikroTiks are RouterOS. **SwOS is a different product line.**

| | RouterOS | SwOS |
|---|---|---|
| Product line | CRS3xx+, CCR, CHR, RB1xxx, etc. | RB260GS, CRS1xx/CRS2xx (older), low-end SOHO |
| Config interface | Full CLI + REST API (v7+) + SSH | **HTTP web UI only** — no SSH, no API |
| Programmatic access | Documented REST, SSH-CLI | Reverse-engineered HTTP POSTs (unofficial) |
| Feature set | Full L2/L3, routing, firewall, BGP, IPsec | Basic L2: VLANs, port speeds, LACP, RSTP |
| Northbound driver | `MikrotikRouterOSDriver` (read + write) | `MikrotikSwOSDriver` (read-only via SNMP) |

---

## 1. Arista EOS (eAPI)

### Connection
- **Protocol**: HTTPS POST to `https://<switch-ip>/command-api`
- **Body**: JSON-RPC 2.0
- **Auth**: HTTP Basic
- **Port**: 443 (default)

### Wire format

Request:
```json
{
  "jsonrpc": "2.0",
  "method": "runCmds",
  "params": {"version": 1, "cmds": ["show version"], "format": "json"},
  "id": "northbound-1"
}
```

### Commit-confirm (write path)

```
configure session northbound-r-001
   interface Ethernet14
      switchport access vlan 200
commit timer 0:01:00       ← commit, auto-rollback in 60s if not confirmed
```

Then within 60s: `commit` to confirm; otherwise auto-revert. Up to **5 uncommitted sessions** can coexist.

### Northbound driver notes
- `apply_change(diff, confirm_seconds=60)` maps to commit-timer flow
- `render_change` returns the literal CLI commands
- `backup_config` = `show running-config`
- Session name = `nb-<request_id>` for audit trace

### Refs
- White paper: `arista-eapi-whitepaper.pdf`
- [EOS Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands)
- [eAPI 101](https://arista.my.site.com/AristaCommunity/s/article/arista-eapi-101)

---

## 2. MikroTik RouterOS v7+ (REST + SSH)

### REST API
- **Base URL**: `https://<router-ip>/rest/`
- **Auth**: HTTP Basic
- **Min version**: 7.1beta4

```
GET    /rest/interface
GET    /rest/interface/ethernet
GET    /rest/interface/bridge/vlan
PATCH  /rest/interface/ethernet/.id
POST   /rest/interface/bridge/vlan
```

### SSH fallback
```
ssh admin@<router> '/interface print'
ssh admin@<router> '/export verbose'              ← full running config
ssh admin@<router> '/system backup save name=nb-backup'
```

### Commit-confirm reality
**No native commit-confirm via REST.** Safe mode exists only at SSH terminal. Strategy:
1. Backup before apply (`/system backup save`)
2. Apply via REST
3. Verify reachability post-apply
4. If unreachable → manual rollback (caller restores backup)

### Refs
- [RouterOS REST API](https://help.mikrotik.com/docs/spaces/ROS/pages/47579162/REST+API)

---

## 3. MikroTik SwOS (HTTP form-POST scraping)

### Reality
- **NO official API**
- Only HTTP web UI
- Reverse-engineered endpoints exist; firmware-bump fragile
- Community-maintained, no canonical docs

### Best-effort endpoints (unsupported)
```
GET  http://<switch>/sys.b          → system info
GET  http://<switch>/link.b         → link/port info
POST http://<switch>/link.b         → set port speed, VLAN
GET  http://<switch>/vlan.b         → VLAN table
```

Body format: form-encoded with hex-encoded numeric fields.

### Northbound driver decision
- **Read-only forever.** `capabilities.writable = False`.
- Read path: **SNMP** (IF-MIB + BRIDGE-MIB + MIKROTIK-MIB) — vendor-supported.
- HTTP scrape used **only** to snapshot a config blob for `backup_config()`.
- No `apply_change`. Vendor UI deep-link button instead.

### Refs
- [SwOS docs index](https://help.mikrotik.com/docs/spaces/SWOS/pages/328415/SwOS)

---

## 4. Pica8 PicOS (NETCONF + SSH)

### NETCONF
- **Port**: 830 (NETCONF default)
- **Python lib**: `ncclient` (sync; wrap in threadpool for async)

```python
from ncclient import manager
mgr = manager.connect(
    host="10.20.0.12", port=830,
    username="admin", password="...",
    hostkey_verify=False,
    device_params={"name": "default"},
)
```

### Core YANG models
- `vlan.yang` — VLAN table + members
- `interfaces.yang` — port admin state, description, mode
- `bgp.yang` — BGP peers
- `system.yang` — hostname, syslog

### Confirmed-commit
```python
mgr.commit(confirmed=True, timeout=60)    # candidate → running, auto-revert in 60s
mgr.commit()                              # confirm; otherwise reverts
```

Default timeout 10 min; Northbound sets 60s to match Arista.

### Known gotcha
Older `ncclient` requires `rpc.py` monkeypatch for PicOS. Verify against current ncclient + current PicOS firmware in lab.

### Northbound driver notes
- `apply_change(diff, confirm_seconds=60)` → `commit(confirmed=True, timeout=60)`
- `render_change` builds `<edit-config>` XML
- `backup_config` = `<get-config><source><running/></source></get-config>`
- Wrap all ncclient calls in `asyncio.run_in_executor`
- Per-driver concurrency: 1

### Refs
- Datasheet: `pica8-enterprise-datasheet.pdf`
- [Configuring NETCONF (PicOS 4.4.4)](https://pica8-fs.atlassian.net/wiki/spaces/PicOS444/pages/70687353/Configuring+NETCONF)
- [Commit Confirmed (PicOS 4.5)](https://pica8-fs.atlassian.net/wiki/spaces/PicOS45/pages/258613628/Commit+Confirmed)

---

## 5. FreeBSD (SSH read-only)

### Connection
- **Protocol**: SSH
- **Auth**: SSH key strongly preferred
- **Python lib**: `asyncssh`

### Read targets
```bash
ifconfig -a
cat /etc/rc.conf | grep -E "ifconfig_|vlans_"
netstat -rn
cat /etc/pf.conf                                  # firewall
vtysh -c "show running-config"                    # FRR (if installed)
vtysh -c "show ip bgp summary"
```

### Write path
**None.** `role in (router, vpn)` is read-only forever. Driver `writable=False`.

---

## Driver capability matrix (target defaults)

| Platform | `writable` | `commit_confirm` | `snmp_read` | `lldp` | `max_conc` | `auth_methods` | `web_ui_url_template` |
|---|---|---|---|---|---|---|---|
| `mikrotik_routeros` | ✓ | ✗ | optional | ✓ | 5 / 1 | password, api_token | `http://{mgmt_ip}/webfig/` |
| `mikrotik_swos` | **✗** | n/a | **required** | ✓ via SNMP | 1 | password, snmp_v2c_community | `http://{mgmt_ip}/` |
| `arista` | ✓ | ✓ | optional | ✓ | 5 | password | `https://{mgmt_ip}/` |
| `pica8` | ✓ | ✓ | optional | ✓ | 1 | password, ssh_key | `https://{mgmt_ip}:8888/` |
| `freebsd` | **✗** | n/a | ✗ | ✗ | 1 | ssh_key | `null` (SSH chip) |

## Open questions

1. **Lab access**: do we have any reachable test switches we can use to record fixtures for the driver test harness?
2. **Per-device API enable**: enabling eAPI / REST / NETCONF on each device is one-time admin work. Onboarding wizard should warn / document this.
3. **SwOS lab device**: do you have a reachable SwOS unit for SNMP-walk fixture recording, or do we synthesize from MIB definitions?
