# Northbound — driver validation status (honest)

Last updated: 2026-05-30. Source of truth for **what has actually been
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
| Pica8 PicOS | `pica8` | ✓ | **authored** (XML) | ✗ **blocked** | none | No free/public PicOS image exists anywhere. |

## Transport layer status

The driver parsers are blocked on images, but transports are validatable
independently. One was exercised live in this build:

| Transport | Used by | Live-validated | Against | Result |
|---|---|---|---|---|
| `asyncssh_client.SshClient` | FreeBSD/FRR read path, RouterOS SSH fallback, Cisco SSH fallback | ✓ **yes** | **FRR 9.1** (Alpine) container over SSH | PASS — real `vtysh -c "show running-config"` + `show ip bgp summary` returned and decoded |
| `httpx_client.HttpxClient` | Arista eAPI, Cisco NX-API | partial | mock transport only | unit-tested; eAPI/NX-API wire untested against a live API |
| `netconf_client.NetconfClient` | Pica8 NETCONF | ✗ | — | unit-tested vs a fake manager only |
| `snmp_client.SnmpClient` | SwOS, optional fallbacks | ✗ | — | record-replay tested only |

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
- Freely pullable: `quay.io/frrouting/frr:9.1.0`, `alpine:latest`. ✓
- containerlab: installed 0.75.0 via official script. ✓
- cEOS / NX-OSv / PicOS: **not obtainable** (auth/licence/no-image). ✗

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
