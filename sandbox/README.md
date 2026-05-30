# Northbound driver-validation sandbox

A containerlab sandbox to validate Northbound drivers against **real**
network-OS instances, closing the "structurally-correct-but-behaviorally-
unverified" gap flagged in the validation gate.

> **Honest status (build sandbox, 2026-05):** of the three network-backed
> drivers, only the **SSH transport** was live-validated here, against a real
> **FRR 9.1** node (Alpine) over SSH — see `validate_ssh.py`. Arista cEOS,
> Cisco NX-OS, and Pica8 PicOS all require auth/licensed images that are **not
> obtainable in this environment** (cEOS needs an arista.com login; NX-OSv
> needs licensed qcow + KVM nesting; Pica8 has no public image). Those drivers
> remain fixture-only. Full per-driver truth: `../supporting material/vendor-docs/validation-status.md`.
>
> Everything here is built to run *the moment an operator supplies a cEOS
> image* — the topology, scripts, and record harness are image-parameterized.

## What's here

| File | Purpose |
|---|---|
| `topology.clab.yml` | containerlab topology: cEOS + FRR + 2 Linux hosts, image refs parameterized |
| `bring-up.sh` | deploy (containerlab, or raw `docker run` fallback), enable eAPI on cEOS, print mgmt IPs |
| `tear-down.sh` | destroy the lab + any docker-run fallback containers/network |
| `record_fixtures.py` | **NB_RECORD harness** — capture RAW device responses into `tests/fixtures/<platform>/*.captured.*` |
| `validate_ssh.py` | live SSH-transport validator (FRR/FreeBSD read path) |
| `files/frr/` | FRR node support: `frr.conf`, `daemons`, `entrypoint.sh` (adds sshd) |

## Prerequisites

- Docker (tested on 20.10)
- containerlab (`bash -c "$(curl -sL https://get.containerlab.dev)"`) — optional;
  scripts fall back to raw `docker run` for the FRR/host path if absent
- ~3 GB free for FRR + hosts; cEOS adds ~2 GB and ~1 GB RAM per node

## Quick start (FRR/SSH path — works with freely-pullable images)

```bash
# from repo root
FRR_ONLY=1 sandbox/bring-up.sh          # brings up FRR + a host, prints mgmt IPs
source .venv/bin/activate
python sandbox/validate_ssh.py --host <frr1-ip> --username nbadmin --password nbsandbox
sandbox/tear-down.sh
```

Expected: `SSH transport live validation: PASS — real device output received.`
This drives `northbound._lib.transport.asyncssh_client.SshClient` against a
real FRR `vtysh` over SSH — the exact transport the FreeBSD/FRR read path uses.

You can also run the gated live transport test directly:

```bash
NB_LIVE_SSH_HOST=<frr1-ip> pytest tests/_lib/transport/test_asyncssh_client.py -k live -v
```

(It `skip`s when `NB_LIVE_SSH_HOST` is unset, keeping the default suite hermetic.)

## Full path — Arista cEOS (operator supplies the image)

cEOS is gated behind an arista.com login and cannot be pulled here. When you
have it:

1. **Obtain cEOS-lab** from <https://www.arista.com/en/support/software-download>
   (Software Download → cEOS-lab → `cEOS-lab-<ver>.tar.xz`). Requires a free
   arista.com account.

2. **Import it as a docker image:**
   ```bash
   docker import cEOS-lab-4.32.0F.tar.xz ceos:4.32.0F
   docker images | grep ceos     # confirm
   ```

3. **Deploy the full topology:**
   ```bash
   CEOS_IMAGE=ceos:4.32.0F sandbox/bring-up.sh
   ```
   The startup-config in `topology.clab.yml` enables `management api
   http-commands` (eAPI over HTTP) and creates `admin`/`nbsandbox`.
   `bring-up.sh` also runs an idempotent enable step and prints the mgmt IP.

4. **Validate the Arista driver against the live box & re-record fixtures:**
   ```bash
   source .venv/bin/activate
   python sandbox/record_fixtures.py --platform arista --host <ceos1-ip> \
       --username admin --password nbsandbox --scheme http
   ```
   This instantiates the **real** `AristaDriver` (real eAPI, no mock),
   exercises `test_credentials` / `get_running_config` / `get_ports` /
   `get_neighbors` / `render_change(dry)`, and writes the **raw eAPI JSON**
   responses to `tests/fixtures/arista/<command>.captured.json` with a
   provenance header (model, EOS version, capture timestamp, host).

5. **Diff captured vs authored — every mismatch is a real parser bug:**
   ```bash
   python sandbox/record_fixtures.py --diff --platform arista
   ```
   Compare the captured `raw_responses[]` blobs against the hand-authored
   `tests/fixtures/arista/*.json`. Field-name / nesting / value divergences
   in keys the parser reads (`interfaceStatus`, `lldpNeighbors` nesting,
   `switchportInfo.*`, `commit timer` acceptance) are parser bugs — fix them
   in `src/northbound/drivers/arista.py`, replace the authored fixture with
   the captured one, update the contract suite, and re-run `make check`.

6. **Tear down:** `sandbox/tear-down.sh`

## Cisco NX-OS / Pica8 PicOS

- **Cisco NX-OSv**: needs a licensed qcow image wrapped via vrnetlab and KVM
  nesting. If you have it, build `vrnetlab/vr-nxos` and add a node to
  `topology.clab.yml`, then `record_fixtures.py --platform cisco ...`.
- **Pica8 PicOS**: no public image exists. If you have a real PicOS device or
  VM reachable over NETCONF (830), point the recorder at it:
  `record_fixtures.py --platform pica8 --host <ip> --username admin --password ...`
  → writes raw NETCONF XML to `tests/fixtures/pica8/get_config_running.captured.xml`.

## Resource notes

- FRR + 2 alpine hosts: ~250 MB RAM, ~400 MB disk total.
- cEOS: ~1 GB RAM and ~1.5 GB disk per node; budget accordingly.
- Always `tear-down.sh` when done — containers otherwise persist across reboots.

## Cleanup guarantee

`tear-down.sh` is idempotent: it destroys the containerlab lab (both the full
and FRR-only generated topology) and removes the raw `docker run` fallback
containers (`nb-frr1`, `nb-host1`) and the `nb-sandbox` network.
