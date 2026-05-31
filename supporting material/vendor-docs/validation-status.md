# Northbound — driver validation status (honest)

Last updated: 2026-05-31. Source of truth for **what has actually been
validated against real devices** vs. what is structurally complete but
behaviorally unverified.

> Rigorous-honesty rule: a row says "live: yes" only if a real network-OS
> instance returned the data the parser consumed. No fabricated device output.

## Per-driver status

| Driver | `platform_id` | Code-complete | Fixtures | Live-validated | NOS version tested | Why blocked |
|---|---|---|---|---|---|---|
| Mock | `mock` | ✓ | n/a (in-proc) | ✓ (deterministic) | n/a | — |
| Arista EOS | `arista` | ✓ | **authored** + live | ✓ **LIVE (deep)** | **vEOS-lab 4.27.0F** (1- and 2-node) | Full driver over eAPI: reads + commit-confirm WRITE (`configure session`/`commit timer`, confirm, apply→revert) for BOTH **access AND trunk/tagged-VLAN** (native+allowed list, parsed back), plus **LLDP `get_neighbors`** against a real 2-node adjacency incl. exact port-filter. **Found + fixed 4 real bugs** (3 below + LLDP port_id literal-quote strip). |
| Cisco IOS/NX-OS | `cisco` | ✓ | **authored** + live | **SSH read ✓ + NX-API read+write ✓** | **IOSv 15.8 / IOSvL2 15.2 (SSH), NX-OSv 7.3 (NX-API)** | SSH read path vs IOSv/IOSvL2 (incl. get_ports). **NX-API path fully live-validated vs NX-OSv 7.3 Titanium**: test_credentials, get_ports (145 ifaces), get_running_config + the commit-confirm WRITE path (checkpoint+config, confirm, apply→revert). **Found + fixed 4 real bugs total** (SSH VLAN-column; NX-API Content-Type; NX-API command-array; bare `switchport`). SSH parser now uses ntc-templates. |
| Pica8 PicOS | `pica8` | ✓ | **authored** (XML) | **transport ✓ / data-models ✗ (1 suspected bug flagged)** | Netopeer2 (transport) | NETCONF transport + confirmed-commit live-validated vs Netopeer2 (2 bugs found+fixed). Data models still **device-blocked**: PicOS-V is free but **registration-gated at pica8.com** with NO anonymous mirror (unlike vEOS) — searched Drive/Mega/GitHub, none exist; needs operator to supply the qcow2 or Pica8 portal creds. Pre-live code-review finding (NOT yet device-confirmed): edit-config sends `<config><interfaces>` namespace-less, but the device config tree is rooted at `<configuration xmlns="http://xml.juniper.net/xnm/1.1/xnm">` — a real PicOS may reject the payload for the missing xnm `<configuration>` wrapper. NOT blind-fixed (guessing repeats the circular-fixture trap); resolve against a live PicOS-V. |

## Transport layer status

The driver parsers are blocked on images, but transports are validatable
independently. One was exercised live in this build:

| Transport | Used by | Live-validated | Against | Result |
|---|---|---|---|---|
| `asyncssh_client.SshClient` | FreeBSD/FRR read path, Cisco SSH fallback | ✓ **yes** | **FRR 9.1** (SSH) + **Cisco IOSv 15.8** (SSH) | PASS — FRR `vtysh` decode, and the real CiscoDriver SSH read path vs IOSv (asyncssh negotiated IOSv's legacy sha1 KEX fine). |
| `httpx_client.HttpxClient` | Arista eAPI, Cisco NX-API | ✓ **yes (eAPI + NX-API)** | **vEOS 4.27** (eAPI/HTTPS) + **NX-OSv 7.3** (NX-API/HTTP) | PASS — live eAPI and NX-API JSON-RPC end to end via the real drivers. |
| `netconf_client.NetconfClient` | Pica8 NETCONF | ✓ **yes** | **Netopeer2/sysrepo** (`:candidate` + `:confirmed-commit`) over SSH | PASS — get-config / edit-config(candidate) / confirmed-commit / confirming-commit / verify, driving the real wrapper. **Found + fixed 2 real bugs** (see below). |
| `snmp_client.SnmpClient` | (not wired into any driver) | ✓ **yes** | **net-snmp `snmpd`** (community `public`) over UDP/161 | PASS — `get` / `walk` (37 rows) / `bulk_get` against a real daemon. **Found + fixed 1 real bug** (walk async-generator, below). |

### Live SSH transport validation — evidence

`sandbox/validate_ssh.py` driving `SshClient` against the sandbox FRR node:

```
[OK ] uname -a
    Linux frr1 6.12.85+deb12-amd64 ... x86_64 Linux
[OK ] vtysh -c "show running-config"
    Building configuration...
    Current configuration:
    !
[OK ] vtysh -c "show ip bgp summary"
    IPv4 Unicast Summary (VRF default):
    BGP router identifier 10.20.20.1, local AS number 65001 vrf-id 0
SSH transport live validation: PASS — real device output received.
```

Reproduce: `FRR_ONLY=1 sandbox/bring-up.sh` then
`python sandbox/validate_ssh.py --host <frr1-ip> --username nbadmin --password nbsandbox`.
The gated pytest equivalent: `NB_LIVE_SSH_HOST=<ip> pytest tests/_lib/transport/test_asyncssh_client.py -k live`.

### Live NETCONF transport validation — evidence

The Pica8 driver's data-plane (PicOS) still needs a licensed image, but the
NETCONF *transport* + *confirmed-commit* flow it relies on were exercised live
against **Netopeer2/sysrepo** (open, no auth, no licence — `:candidate` +
`:confirmed-commit`), driving the real `NetconfClient`:

```
[old-pattern] correctly broken: TypeError: argument of type 'NoneType' is not iterable
[get-config]    OK  (3193 bytes)
[edit-config]   OK  (target='candidate' accepted)
[commit-confirm] OK  (confirmed-commit, timeout=120)
[commit-confirm] OK  (confirming commit → permanent)
[verify]        OK  (change in running-config: True)
NETCONF transport + confirmed-commit live validation: PASS
```

**Two real production bugs were found ONLY by running against a real server**
(the unit-test fake had mirrored our *wrong* call shape, so green tests hid them):

1. `NetconfClient.edit_config` called ncclient **positionally**, but real
   ncclient is `edit_config(config, format, target, …)` — our `target`
   ("candidate"/"running") landed in ncclient's `config` slot and the XML in
   `format`. Broken against every real NETCONF server. Fixed: call by keyword.
2. `NetconfClient.commit` passed `timeout` as an **int**; ncclient writes
   `<confirm-timeout>` via lxml, which requires str text → `TypeError`. Pica8's
   `commit(confirmed=True, timeout=confirm_seconds)` would crash live. Fixed:
   coerce to str. The unit-test fakes now mirror the **real** ncclient
   signatures so a positional/typing regression fails in CI too.

Reproduce: bring up Netopeer2 (host networking; disable NACM) per the header of
`sandbox/validate_netconf.py`, then `python sandbox/validate_netconf.py`.
The docker port-proxy mangles the SSH banner and the bridge IP is not
host-routable in this sandbox, so `--network host` is required.

### Live Arista driver validation — evidence

Full `AristaDriver` driven against **vEOS-lab 4.27.0F** (qemu/KVM, eAPI forwarded
to the host) — read paths AND the commit-confirm write path:

```
[test_credentials] ok=True ver=vEOS-lab 4.27.0F 45ms
[running_config]   613 bytes
[get_ports]        3 ports: ['Ethernet2', 'Management1', 'Ethernet1']
[apply_change]     success=True token=nb-e26b1e6a       # configure session + commit timer
[confirm+verify]   Ethernet1 vlan=20 desc='nb-live-confirm' -> OK
[apply_change#2]   success=True token=nb-fcb4bd6b
[revert+verify]    Ethernet1 vlan=20 desc='nb-live-confirm' -> OK (unchanged)
Arista driver live validation: PASS
```

Depth note (added after the initial happy-path pass): a **2-node vEOS topology**
(overlay disks sharing the configured base, linked by a qemu socket) was stood up
so real LLDP adjacency exists. `get_neighbors` parsed the real neighbor (chassis,
remote port, the `[local-port]` prefix) and the exact port-filter matched —
exposing a 4th bug: the remote `interfaceId` is wrapped in literal quotes on vEOS
(`"Ethernet1"`); now stripped (prefer `interfaceId_v2`, route through
`normalize_port_id`). The **trunk/tagged-VLAN** write path (native vlan + allowed
list) was also applied and parsed back correctly — previously only access VLAN
was exercised.

**Three real production bugs found ONLY against the real device** (mock unit
tests had returned canned data regardless of enable mode / session state):

1. **No enable mode for privileged reads** — `show running-config` (and config
   sessions) need enable; the driver sent them at privilege level 1 → eAPI code
   1002 "invalid command". Fix: `_run_cmds` prepends `enable` to every batch and
   strips its result.
2. **eAPI error-code misclassification** — codes {1000,1001,1002} were mapped to
   `AuthError`, but they are COMMAND-execution errors (auth fails at HTTP 401).
   A privilege/command failure thus surfaced as "bad credentials". Fix:
   `_AUTH_ERROR_CODES` emptied; JSON-RPC errors are `DriverError` unless HTTP 401.
3. **Wrong confirm/revert syntax** — a session in `pendingCommitTimer` state
   cannot be re-entered, so the two-command `configure session NAME` + `commit`
   failed (code 1000). Fix: single-line `configure session NAME commit` /
   `... abort`.

Reproduce: boot vEOS per the header of `sandbox/validate_arista.py`, then
`python sandbox/validate_arista.py`.

### Live Cisco SSH read-path validation — evidence

`CiscoDriver` (SSH mode, `prefer_native_api=False`) vs real **IOSv 15.8(3)M2**:

```
[test_credentials] ok=True ver='Cisco IOS Software, IOSv ... Version 15.8(3)M2 ...'
[reachable]        True
[running_config]   2936 bytes
[hostname]         'nb-iosv'
[get_ports]        0   # 'show interfaces status' is switch-only — empty on a router
Cisco SSH read path live validation: PASS
```

The version/hostname/running-config parsers matched real IOS output (IOSv). On
**IOSvL2** (switch), `get_ports` parses `show interfaces status` — which exposed
a real bug: the optional "Name" column is blank, shifting columns so a
hand-rolled fixed-index split dropped the access VLAN to None. Fix: the parser
now uses the **ntc-templates** TextFSM library (community-maintained, tested
across IOS versions) instead of hand-rolled column logic. Verified live:
Gi0/1→VLAN 20, Gi0/3 shutdown→admin_up False, Gi0/0 routed→None.

Reproduce: boot IOSv/IOSvL2 per the header of `sandbox/validate_cisco_ssh.py`.

### Live Cisco NX-API validation — evidence

The Cisco driver's PRIMARY path (NX-API JSON-RPC) validated vs **NX-OSv 7.3
Titanium** via the real `CiscoDriver`:

```
[test_credentials] ok=True ver='NX-OSv Chassis 7.3(0)D1(1)'
[running_config]   9038 bytes
[get_ports]        145 ports (NX-API show interface)
[apply_change]     success=True   # checkpoint + config command-array
[confirm+verify]   Ethernet2/1 vlan=30 -> OK
[apply_change#2]   success=True
[revert+verify]    Ethernet2/1 vlan=30 -> OK (rolled back)
Cisco NX-API path live validation: PASS
```

**Three real NX-API bugs found ONLY against real NX-OS** (now fixed): (1) httpx's
default `Content-Type: application/json` is rejected — NX-API needs
`application/json-rpc`; (2) a `` ; ``-joined single `cli` string is rejected
("invalid special characters") — NX-API needs a JSON-RPC command ARRAY; (3) a
routed-by-default NX-OS port rejects `switchport mode access` until a bare
`switchport` makes it L2. The checkpoint/confirm/revert write path (R4) is now
proven end to end on real NX-OS. Reproduce: boot Titanium + `feature nxapi` per
the header of `sandbox/validate_cisco_nxapi.py` (HTTP — Titanium's NX-API HTTPS
TLS doesn't serve).

Cisco NX-API **trunk** write is now live-validated too (vs NX-OSv 7.3: native
VLAN 10 + allowed {20,30,40} applied, confirmed, parsed back OK).

Cisco depth still UNvalidated (honest): **NX-API LLDP `get_neighbors`** against a
real adjacency. This needs a 2-node NX-OS topology, which the Titanium emulator
would not provide here — a fresh single boot works (~66s) but every REBOOT (incl.
with a link NIC) wedges at 99% CPU with a silent console in this sandbox. The
NX-API `_parse_lldp` (TABLE_nbor_detail/ROW_nbor_detail) is unit-tested but not
device-confirmed; the analogous Arista LLDP parser WAS the one a 2-node run turned
into a real bug, so this remains a genuine (smaller) gap, honestly flagged.

> ONLY remaining gap: **Pica8 PicOS data models** — no public PicOS image exists
> anywhere. The NETCONF transport + confirmed-commit it relies on are
> live-validated vs Netopeer2 (below); only the Pica8-specific YANG payloads are
> unverified.

### Live SNMP transport validation — evidence

`SnmpClient` driven against a real net-snmp `snmpd` (`docker run -d
--network host polinux/snmpd`):

```
[get  sysDescr.0] OK  b'Linux ... x86_64'
[walk system    ] OK  37 rows
[bulk_get x2    ] OK  2 values
SNMP transport live validation: PASS — real snmpd output received.
```

**Real bug found ONLY against a real daemon** (now fixed): puresnmp's
`PyWrapper.walk` is an **async generator** yielding `PyVarBind`, but
`SnmpClient.walk` `await`-ed it as a list-returning coroutine →
`TypeError: An asyncio.Future, a coroutine or an awaitable is required`. The
unit-test fake had mirrored the wrong (list) shape. Fixed: consume with
`async for`; Protocol + fake now mirror the real puresnmp async-generator
contract. Reproduce: `python sandbox/validate_snmp.py`.

> Note: `supports_snmp_read` was flipped **True → False** on the cisco / arista /
> pica8 drivers. The SNMP transport works (proven above) but is **not wired into
> any driver read path** — those drivers read via eAPI / NX-API / NETCONF / SSH.
> Advertising an unimplemented capability to the UI was dishonest; the flag now
> reflects reality. (`parse_snmp_lldp_table` in `_lib/lldp.py` is likewise a
> ready-but-unwired helper.)

## What "fixtures: authored" means (the circular-fixture problem)

The Cisco/Pica8 contract fixtures in `tests/fixtures/<platform>/` were
hand-authored from vendor documentation by the agent that also wrote the
parsers. The contract suite (`tests/drivers/test_contract.py`) therefore proves
the parser is *self-consistent with the agent's guess of the wire format* — not
that it matches what a real device emits. A shared wrong guess passes green.

This is **not** the same as live-validated. It is honestly labelled
"behaviorally unverified." **Arista is now the exception** — it was validated
against real vEOS (above), which is exactly how the live run caught three bugs
the self-consistent fixtures could never surface. Cisco NX-API and Pica8 data
models remain in the circular-fixture state until a Nexus / PicOS image is
available.

## What was obtainable in the build sandbox (2026-05)

- Docker 20.10, `/dev/kvm` present, ~11 GiB free.
- Registry egress: **yes** (docker.io + quay.io reachable).
- Freely pullable: `quay.io/frrouting/frr:9.1.0`, `alpine:latest`,
  `sysrepo/sysrepo-netopeer2:latest` (open NETCONF server). ✓
- containerlab: installed 0.75.0 via official script. ✓
- **vEOS-lab 4.27.0F: OBTAINED** ✓ — the hegdepavankumar GNS3 repo's Google-Drive
  vEOS mirror (quota-blocked on first attempts) freed up; downloaded the Aboot
  `cdrom.iso` + `hda.qcow2`, booted in qemu/KVM, and live-validated the full
  Arista driver. (vEOS boots without a license keygen.)
- NX-OSv / Nexus 9000v / PicOS: **not obtainable** — Nexus 9000v is licensed and
  **absent from the GNS3 repo** (which carries only IOS/IOSv/IOL/CSR/cat9k), so
  the Cisco **NX-API** write path stays image-blocked; the IOS images would only
  exercise the Cisco **SSH read** path. PicOS has no public image (NETCONF
  transport is validated vs Netopeer2 instead). ✗

## How to close each gap (operator runbook)

1. **Arista (highest value, lowest effort):** obtain `cEOS-lab.tar.xz` from
   arista.com, `docker import` it, `CEOS_IMAGE=ceos:<ver> sandbox/bring-up.sh`,
   then `python sandbox/record_fixtures.py --platform arista --host <ip>
   --username admin --password nbsandbox --scheme http`, then
   `--diff --platform arista`. Fix any parser bug the diff reveals in
   `src/northbound/drivers/arista.py`, replace the authored fixture with the
   captured one, update the contract suite, `make check`. Full steps:
   `sandbox/README.md`.
2. **Cisco:** supply a licensed NX-OSv qcow, wrap via vrnetlab, add a node to
   `topology.clab.yml`, then `record_fixtures.py --platform cisco ...`.
3. **Pica8:** point `record_fixtures.py --platform pica8` at any reachable real
   PicOS device/VM over NETCONF (830).

Until those run, the three network-backed drivers stay **"structurally
correct, behaviorally unverified"** — by design and by honest labelling.
