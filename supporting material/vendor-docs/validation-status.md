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
| Arista EOS | `arista` | ✓ | **authored** + live | ✓ **LIVE** | **vEOS-lab 4.27.0F** (qemu/KVM) | Full driver validated over eAPI: test_credentials / get_ports / get_running_config + the commit-confirm WRITE path (`configure session` + `commit timer`, confirm, **and** apply→revert). **Found + fixed 3 real bugs** (see below). |
| Cisco NX-OS | `cisco` | ✓ | **authored** | ✗ **blocked** | none | NX-API write path needs a Nexus 9000v image (licensed; absent from the GNS3 image repo, which carries only IOS/IOSv/IOL/CSR/cat9k). The IOS images would exercise only the Cisco SSH read path, not NX-API. |
| Pica8 PicOS | `pica8` | ✓ | **authored** (XML) | **transport ✓ / data-models ✗** | Netopeer2 (transport) | NETCONF transport + confirmed-commit live-validated vs Netopeer2 (2 bugs found+fixed); PicOS YANG data models still blocked — no free/public PicOS image exists anywhere. |

## Transport layer status

The driver parsers are blocked on images, but transports are validatable
independently. One was exercised live in this build:

| Transport | Used by | Live-validated | Against | Result |
|---|---|---|---|---|
| `asyncssh_client.SshClient` | FreeBSD/FRR read path, Cisco SSH fallback | ✓ **yes** | **FRR 9.1** (Alpine) container over SSH | PASS — real `vtysh -c "show running-config"` + `show ip bgp summary` returned and decoded |
| `httpx_client.HttpxClient` | Arista eAPI, Cisco NX-API | ✓ **yes (eAPI)** | **vEOS-lab 4.27.0F** eAPI over HTTPS | PASS — live eAPI JSON-RPC end to end via the real AristaDriver. NX-API side still untested (no Nexus image). |
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
