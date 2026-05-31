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
| Arista EOS | `arista` | ✓ | **authored** (from vendor docs) | ✗ **blocked** | none | cEOS-lab image requires arista.com login; no public mirror exists (`docker manifest inspect ceos*` → denied). |
| Cisco NX-OS | `cisco` | ✓ | **authored** | ✗ **blocked** | none | NX-OSv needs a licensed qcow + vrnetlab + KVM nesting; no free image. |
| Pica8 PicOS | `pica8` | ✓ | **authored** (XML) | **transport ✓ / data-models ✗** | Netopeer2 (transport) | NETCONF transport + confirmed-commit live-validated vs Netopeer2 (2 bugs found+fixed); PicOS YANG data models still blocked — no free/public PicOS image exists anywhere. |

## Transport layer status

The driver parsers are blocked on images, but transports are validatable
independently. One was exercised live in this build:

| Transport | Used by | Live-validated | Against | Result |
|---|---|---|---|---|
| `asyncssh_client.SshClient` | FreeBSD/FRR read path, Cisco SSH fallback | ✓ **yes** | **FRR 9.1** (Alpine) container over SSH | PASS — real `vtysh -c "show running-config"` + `show ip bgp summary` returned and decoded |
| `httpx_client.HttpxClient` | Arista eAPI, Cisco NX-API | partial | mock transport only | unit-tested; eAPI/NX-API wire untested against a live API |
| `netconf_client.NetconfClient` | Pica8 NETCONF | ✓ **yes** | **Netopeer2/sysrepo** (`:candidate` + `:confirmed-commit`) over SSH | PASS — get-config / edit-config(candidate) / confirmed-commit / confirming-commit / verify, driving the real wrapper. **Found + fixed 2 real bugs** (see below). |
| `snmp_client.SnmpClient` | optional fallbacks | ✗ | — | record-replay tested only |

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

## What "fixtures: authored" means (the circular-fixture problem)

The Arista/Cisco/Pica8 contract fixtures in `tests/fixtures/<platform>/` were
hand-authored from vendor documentation by the agent that also wrote the
parsers. The contract suite (`tests/drivers/test_contract.py`) therefore proves
the parser is *self-consistent with the agent's guess of the wire format* — not
that it matches what a real device emits. A shared wrong guess passes green.

This is **not** the same as live-validated. It is honestly labelled
"behaviorally unverified."

## What was obtainable in the build sandbox (2026-05)

- Docker 20.10, `/dev/kvm` present, ~11 GiB free.
- Registry egress: **yes** (docker.io + quay.io reachable).
- Freely pullable: `quay.io/frrouting/frr:9.1.0`, `alpine:latest`,
  `sysrepo/sysrepo-netopeer2:latest` (open NETCONF server). ✓
- containerlab: installed 0.75.0 via official script. ✓
- cEOS / vEOS / NX-OSv (Nexus) / PicOS: **not obtainable** — cEOS/vEOS need an
  arista.com login (no public registry; the widely-linked Google-Drive vEOS
  mirrors are all quota-blocked), Nexus 9000v is licensed, PicOS has no public
  image. The hegdepavankumar GNS3 repo carries IOS/IOSv/IOL/CSR/cat9k + vEOS
  links but **no Nexus** image — so even with it, the Cisco **NX-API** write
  path (the R4-fixed path) and Pica8 NETCONF data models stay image-blocked;
  the IOS images would only exercise the Cisco **SSH read** path. ✗

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
