# Northbound — Principal Engineering & Solutions Architecture

> Companion to `plan.md` and `pm-plan.md`. This is the architecture lens: the diagram, the decisions that matter, the risks worth losing sleep over.

## System diagram

```
┌──────────────────────────────────────────────────────────┐
│  Browser SPA (Vite, React 18, TS, Tailwind, R3F, drei)   │
│  React Query (server cache) · Zustand (UI state)         │
└────────────────┬─────────────────────────────────────────┘
                 │ HTTPS, JWT bearer
┌────────────────▼─────────────────────────────────────────┐
│  FastAPI (single process, single worker for v1)          │
│  ┌────────────────────────────────────────────────────┐  │
│  │ API routers · auth/RBAC · OpenAPI 3.1              │  │
│  ├────────────────────────────────────────────────────┤  │
│  │ Services: port_state · change_apply · backup       │  │
│  │           onboarding · cred_vault · notifications  │  │
│  ├────────────────────────────────────────────────────┤  │
│  │ Driver registry (plugin shape)                     │  │
│  │  Mock | MikroTik | Arista | Pica8 | FreeBSD-RO     │  │
│  ├────────────────────────────────────────────────────┤  │
│  │ APScheduler (in-proc) · Reconciler loop            │  │
│  └────────────────────────────────────────────────────┘  │
│      │             │             │             │         │
│  asyncssh      httpx          ncclient      asyncssh     │
│  (RouterOS    (eAPI/REST)   (NETCONF,      (FreeBSD,     │
│   SSH)                       threadpool)    read-only)   │
└──────┼─────────────┼─────────────┼─────────────┼─────────┘
       ▼             ▼             ▼             ▼
   [devices on lab/dc network]

   Persistence:
     SQLite (aiosqlite, WAL mode) — humans, requests, audit, encrypted creds
     Filesystem — config_backups raw text, audit hash chain
     In-mem dict — port_state cache (30s TTL, single-worker)
```

## Two tracks

| Track | Scope | Status |
|---|---|---|
| **Track 1 (primary, blocking)** | Switches backend + UI: read → request → apply | Always-priority |
| **Track 2 (secondary, parallel)** | Cliq + Zoho Mail integrations | Starts only after M1 ships |

If Track 1 slips, Track 2 freezes.

## Hard rules (non-negotiable)

1. **`role in (router, vpn)` → read-only forever, no admin override.** Enforced at four layers: driver, API, DB constraint, UI.
2. **Every write to a device must be reversible.** Backup before push; commit-confirm where the platform supports it; manual rollback button where it doesn't.
3. **Apply flow state machine is persisted, never in-memory only.** Process restart must not lose track of in-flight changes.
4. **No plaintext credentials anywhere on disk.** Encrypted at rest, redacted in logs, never in audit `before`/`after` JSON.
5. **The audit log is append-only and tamper-evident** (hash chain, nightly verifier).

## The decisions that matter (decide now or pay later)

### D1. Driver layer is async-first, sync-isolated
- All driver methods declared `async def`.
- `ncclient` (NETCONF) is sync → wrap in `loop.run_in_executor` with bounded threadpool (max 8 workers).
- Per-driver `max_concurrency` semaphore (some switches reject concurrent SSH sessions). Default: SSH=1, REST=5.
- **Why:** mixed concurrency is the single biggest source of "works in dev, hangs in prod."

### D2. State of truth model — strict
| Data | Truth | Cache | TTL | Invalidate on |
|---|---|---|---|---|
| Live port state (VLAN, up/down, services) | device | in-mem dict | 30s | apply success, manual refresh |
| Running config | device | in-mem (per-device) | 30s | apply success, manual refresh |
| Reachability | device | in-mem map | 60s (poll) | poll cycle |
| Port metadata (host_model, bmc_ip, notes) | DB | n/a | — | direct edit, applied request |
| Requests, audit, backups | DB | n/a | — | n/a |

Single-worker invariant for v1 → cache fragmentation impossible. Document upgrade path: when scaling to N workers, swap dict → Redis. API surface unchanged.

### D3. Apply flow is a persisted state machine
States: `pending → approved → applying → awaiting_confirm → applied | failed | reverted`.

Every transition writes a row to `change_request_events` with timestamp, actor, payload.

**Recovery by reconciler loop:**
- App restart mid-apply → reconciler reads requests in `applying` or `awaiting_confirm`, picks up where left off.
- `awaiting_confirm` past deadline → reconciler triggers revert path.

**Why mandatory:** crash during apply must never leave a switch in unknown state. Trust ladder collapses on first ghost-failed change.

### D4. Commit-confirm is durable
- Apply with platform-native commit-confirm where supported (Arista session timer, Pica8 NETCONF confirmed-commit).
- Window deadline persisted on the request row (`confirm_deadline_at`).
- Reconciler runs every 10s. Process restart, network blip, crashed worker — confirm window still honored.
- FreeBSD: read-only, never enters this path.
- MikroTik: no native commit-confirm. Strategy = backup-then-apply with safe-mode + manual rollback button (no auto-revert). UI shows this difference loudly.

### D5. CredVault is an interface, default Fernet
```python
class CredVault(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> bytes: ...
    def rotate_master(self) -> None: ...
```
Default impl: Fernet, master key from `NB_MASTER_KEY` env.

Production swap-in: AWS KMS / HashiCorp Vault / SOPS — same interface, no API/router changes.

**Threat model:**
- DB dump → ciphertext only, useless without master
- Process memory dump → plaintext present briefly during driver call (accept risk)
- Master key leak → all creds compromised, rotate procedure required
- Logs → redacted at structlog processor layer; mandatory `SECRET` marker on cred fields

Audit log NEVER stores plaintext. Cred-related audit entries record action only (`cred.created`, `cred.rotated`), not value.

### D6. Audit log is tamper-evident
- Append-only at app layer (no UPDATE/DELETE in any code path).
- Hash chain: `row_hash = sha256(prev_hash + row_canonical_json)`.
- Nightly verifier walks chain, alerts on break.
- Cheap insurance for "someone deleted the audit row covering their own mistake."

### D7. Onboarding is transactional
Wizard steps 1–6 are stateless probes. Step 7 (Confirm) is one DB transaction:
1. `INSERT devices`
2. `INSERT port_metadata` × N
3. `INSERT config_backups` (initial baseline)
4. `INSERT audit_log` (`device.onboarded`)
5. Commit

Failure mid-step → rollback. No half-onboarded device. No orphan ports.

Discovery (step 6) runs **before** transaction starts; if discovery fails, no DB hit.

### D8. Frontend ↔ backend contract
- FastAPI emits OpenAPI 3.1.
- Generate **TS types only** (`openapi-typescript`) — not full client.
- Hand-written thin fetch wrapper imports types. Generated clients are rigid on auth/error/retry; types catch shape drift without bloat.
- Versioning: `Accept: application/vnd.northbound+json; v=1` header. Lock v1 before MVP-A ships.

### D9. Deployment topology — one process, one VM, one SQLite
- FastAPI uvicorn 1 worker.
- Static frontend served by FastAPI (`StaticFiles` mount on `/`).
- SQLite WAL mode, 100ms busy_timeout.
- File-based config backups under `/var/lib/northbound/backups/`.
- Behind Tailscale or nginx reverse proxy with TLS.
- **Backup story:** nightly cron `sqlite3 .backup` + `rsync` of `/var/lib/northbound/`.
- Single-VM is correct at this scale. Document split points so future-us doesn't refactor in panic:
  - **Multi-worker** → Redis cache
  - **>100 devices** → Postgres
  - **HA** → split frontend + LB

### D10. Driver fixture-record harness
Each driver has a `RecordReplayTransport` mode:
- **Record:** real call, real response, save canonical JSON → `tests/fixtures/<platform>/<scenario>.json`
- **Replay:** tests run offline, deterministic
- Re-record gated by `NB_RECORD=1` env var

Mandatory before any driver moves out of "experimental" tier. Catches RouterOS REST shape drift between firmware versions.

## Plugin contract (the real shape)

```python
class DriverCapabilities(BaseModel):
    writable: bool
    supports_commit_confirm: bool
    native_api_available: bool
    supports_snmp_read: bool                   # SwOS-driven addition
    supports_lldp: bool                        # LLDP neighbor display
    max_concurrency: int
    auth_methods: list[AuthMethod]             # renamed from auth_kinds; richer enum
    web_ui_url_template: str | None = None     # vendor UI deep-link

class AuthMethod(StrEnum):
    PASSWORD = "password"
    SSH_KEY = "ssh_key"
    API_TOKEN = "api_token"
    SNMP_V2C_COMMUNITY = "snmp_v2c_community"
    SNMP_V3 = "snmp_v3"


@dataclass
class Neighbor:                                # LLDP neighbor info
    chassis_id: str
    port_id: str
    system_name: str | None
    system_description: str | None = None


class Driver(ABC):
    capabilities: ClassVar[DriverCapabilities]
    platform_id: ClassVar[str]                 # registry key

    def __init__(self, conn: ConnectionParams, creds: Credentials): ...

    # onboarding
    async def test_credentials(self) -> TestResult: ...
    async def discover(self) -> DiscoveryResult: ...

    # read
    async def reachable(self) -> bool: ...
    async def get_ports(self) -> list[PortState]: ...
    async def get_running_config(self) -> str: ...
    async def backup_config(self) -> str: ...
    async def get_neighbors(self, port: str | None = None) -> list[Neighbor]: ...

    # write — raise NotSupported if writable=False
    async def render_change(self, port: str, change: PortChange) -> ConfigDiff: ...
    async def apply_change(self, diff: ConfigDiff, *, confirm_seconds: int) -> ApplyResult: ...
    async def confirm(self, apply_token: str) -> None: ...
    async def revert(self, apply_token: str) -> None: ...
```

New platform = subclass + registry entry. Wizard, API, UI all use it generically.

### Driver capability matrix (concrete per-platform defaults)

| Platform ID | writable | commit_confirm | native_api | snmp_read | lldp | max_conc | auth_methods | web_ui_url_template |
|---|---|---|---|---|---|---|---|---|
| `mikrotik_routeros` | ✓ | ✗ (no native; backup-wrap) | ✓ REST | optional | ✓ | 5 REST / 1 SSH | password, api_token | `http://{mgmt_ip}/webfig/` |
| `mikrotik_swos` | **✗ forever** | n/a | ✗ (HTTP scrape only) | **required** | ✓ via SNMP | 1 | password, snmp_v2c_community | `http://{mgmt_ip}/` |
| `arista` | ✓ | ✓ (commit timer) | ✓ eAPI | optional | ✓ via eAPI | 5 | password | `https://{mgmt_ip}/` |
| `pica8` | ✓ | ✓ (NETCONF confirmed-commit) | ✓ NETCONF | optional | ✓ via NETCONF | 1 | password, ssh_key | `https://{mgmt_ip}:8888/` |
| `freebsd` | **✗ forever** | n/a | n/a (SSH only) | ✗ | ✗ | 1 | ssh_key | `null` (show SSH chip) |

### Transport layer (composable)

Drivers compose from shared transport utilities. **Not** "one driver per protocol" — drivers pick what they need.

```
src/northbound/_lib/transport/
├── snmp_client.py        SnmpReader — async wrapper over puresnmp; recorded-replay-aware
├── httpx_client.py       Thin httpx wrapper; auth, timeout, retry, circuit-breaker
├── asyncssh_client.py    Async SSH command runner; key + password auth
├── netconf_client.py     ncclient adapter (sync lib → asyncio.run_in_executor)
└── html_scrape.py        BeautifulSoup + lxml helpers; SwOS HTML form pages
```

Per-driver composition:
- `MikrotikRouterOSDriver` → `httpx_client` (primary) + `asyncssh_client` (fallback) + `snmp_client` (optional)
- `MikrotikSwOSDriver` → `snmp_client` (primary, reads) + `html_scrape` (backup snapshot only)
- `AristaDriver` → `httpx_client` (eAPI) + `snmp_client` (optional)
- `Pica8Driver` → `netconf_client` (primary) + `snmp_client` (optional)
- `FreeBSDDriver` → `asyncssh_client` only

**Why composable**: PM proposed deferring SNMP to M2. Architect overrode — front-loaded as shared transport means later integration is `import SnmpReader` in any driver, not refactoring 5 drivers.

### LLDP architecture

`get_neighbors()` default impl returns `[]`. Each driver overrides where supported.

Implementation paths:
- **Arista**: `show lldp neighbors detail | json` via eAPI
- **RouterOS**: `/ip/neighbor/print` via REST (proprietary discovery, plus LLDP if enabled)
- **Pica8**: NETCONF get on `<lldp>` subtree
- **SwOS**: `LLDP-MIB::lldpRemoteSystemsData` via SNMP walk
- **FreeBSD**: empty list

`_lib/lldp.py` normalizes the various formats into the canonical `Neighbor` dataclass.

UI surfaces neighbors as a collapsible row in PortPanel **only when non-empty**. Display only; never used for auto-onboarding (hard NO per PM).

## Vendor UI deep-link

Northbound is deliberately scoped — when something falls outside (SwOS writes, complex BGP config on Pica8, vendor-specific knobs), the user should escape cleanly to the vendor's own web UI.

### Pattern

Each platform exposes a `web_ui_url_template` in its capabilities. Frontend renders an **"Open in vendor UI ↗"** button on every device detail page and port detail panel. Click opens new tab.

### UX rules

- Button positioned top-right on device detail and port detail
- Text: "Open in vendor UI ↗" (with external-link icon)
- `target="_blank" rel="noopener noreferrer"` mandatory (security)
- Tooltip: "Northbound is scoped — use {VendorName} for advanced changes"
- For port-level details: opens **device-level** vendor UI (vendor URLs rarely deep-link per port)
- For FreeBSD: show `ssh {ssh_user}@{mgmt_ip}` copy-to-clipboard chip instead

### Why this matters (PM angle)

Without escape hatches, Northbound becomes a wall. Colleagues hit a feature Northbound doesn't expose (custom firewall rule, BGP peer, VLAN trunk filtering edge case) and message Avery — defeating the north-star metric.

With the escape hatch, "I need to do X that NB doesn't support" → click → vendor UI → done. **Northbound stays scoped, user stays unblocked.** That's the whole game.

### Anti-pattern to avoid

**Do not iframe** the vendor UI inside NB. Reasons:
- CSP / X-Frame-Options on vendor UIs blocks it
- Auth handoff is brittle (different cookies, sessions)
- Confuses audit trail ("did this change happen in NB or in the iframe?")
- Vendor UIs aren't designed for embedded use

External-tab navigation is the correct shape.

## Onboarding architecture

Drivers are **plugins**, devices are **runtime data**. Admin onboards via UI at any time. No hardcoded device list, no env-var creds.

### Wizard flow (7 steps)
```
1. Platform     → pick from registry
2. Identity     → name, environment, role
3. Connection   → mgmt_ip, port, prefer_native_api
4. Credentials  → username + (password | SSH key | API token)
5. Test         → live probe: reachable? auth works?
6. Discover     → pull port list, current config, services. Show preview.
7. Confirm      → atomic save: device + port_metadata × N + config backup
```

### What "all populated" means on confirm
| Thing | Source | Stored where |
|---|---|---|
| Device row | wizard input | `devices` |
| Encrypted creds | step 4 | encrypted column |
| Port inventory | live device | `port_metadata` rows (empty human fields) |
| Initial running config | live device | `config_backups` (baseline) |
| Parsed host_model / bmc_ip | parser on existing port descriptions | `port_metadata` rows |
| Live state (VLAN, up/down) | live device | NEVER stored — fetched on demand, cached 30s |

## State drift detection

When a request is filed, capture `device_state_fingerprint` (hash of current ports + their VLANs at file time). At apply time, recompute. If different:
- Block apply, surface diff to admin
- Admin must re-confirm with knowledge of new state

Prevents: "I filed at 9am, you applied at 5pm, but at noon someone else changed the same port."

## Architectural risk register

| Risk | When it bites | Mitigation now | Migration trigger |
|---|---|---|---|
| SQLite write contention | >50 concurrent req/s | WAL mode, async session per req | Switch to Postgres |
| Single-worker = SPoF | Always | Document. systemd auto-restart. | Multi-worker + shared cache |
| In-mem cache cold start | After every restart | Background warmer on startup | Persistent cache layer |
| Driver SDK breakage | Vendor firmware update | Recorded fixtures + contract tests | Pin minor versions |
| RouterOS REST shape drift | MikroTik 7.x → 8.x | Per-version parsers, version-detect at onboard | n/a |
| Encrypted col breaks queries | Trying to search by cred field | Don't. Cred is opaque. | n/a |
| Audit log unbounded growth | ~1y operation | Partition by month, archive >12mo | At 1M rows |
| Master key in env var | Process-host compromise | Read once at startup, mlock if possible | Move to KMS |
| 3D render perf with 280-port Pica8 | M1 testing | Instanced meshes, frustum cull, LOD on zoom-out | n/a |
| Apply mid-flight, app crashes | Anytime | DB state machine + reconciler resumes | n/a |
| Stale state apply (UI 30s old) | Race | Fingerprint at file, re-validate at apply | n/a |
| SwOS firmware bump breaks HTTP scrape | Random | Scrape only for opaque backup; if garbage, garbage is what we save (not load-bearing) | n/a |
| SNMP community string in DB | Always | CredVault encrypts; UI labels as secret; audit redacts | n/a |
| LLDP data inconsistent across platforms (chassis-ID, port-ID encoding) | Always | Normalize in `_lib/lldp.py`; recorded fixtures per platform | n/a |
| `puresnmp` upstream breakage | Random | Pin minor version; thin wrapper isolates the dependency | Swap to pysnmp behind same interface |

## Testing pyramid

| Layer | Tool | Scope |
|---|---|---|
| Unit | pytest | Pure logic: parsers, state machine transitions, diff rendering |
| Driver contract | pytest + RecordReplayTransport | Each driver passes the same contract suite against recorded fixtures |
| Service integration | pytest + httpx.AsyncClient + MockDriver | API routes against in-memory driver, real DB |
| State machine | pytest + simulated time | Apply flow with crash injection at each transition |
| End-to-end | Playwright + MockDriver-backed API | Critical user flows (onboard, file, approve, apply) |
| Smoke (lab only) | Manual / scripted | Real MikroTik in lab, weekly |

Coverage targets: services 85%, drivers 70%, state machine 95%.

## Build vs buy

| Capability | Build | Buy/use lib | Why |
|---|---|---|---|
| Auth | build (FastAPI deps + python-jose) | — | Trivial at this scale |
| Driver SDKs | build wrappers around | asyncssh, httpx, ncclient | These are the standards |
| Migration | — | Alembic | Solved problem |
| Crypto | — | cryptography (Fernet) | Never roll your own |
| Scheduler | — | APScheduler | Sufficient for in-proc |
| 3D | — | three.js + R3F + drei | Standards |
| OpenAPI types | — | openapi-typescript | Generated, not hand-maintained |
| State machine | build (~100 LOC) | — | Keeps it grep-able |
| Audit hash chain | build (~30 LOC) | — | Custom semantics |
| Cred vault | build interface, Fernet impl | — | Future-swap to KMS |

## Sequenced wave plan

7-wave plan; each wave is shippable, tested, and unblocks the next.

| Wave | Scope | Duration |
|---|---|---|
| **A. Backend foundation** | `_lib/transport/{snmp,httpx,asyncssh,netconf,html_scrape}.py`, Driver ABC + dataclasses, registry, MockDriver, `GET /api/platforms` | 1–2 d |
| **B. MikrotikRouterOS read path** | REST primary + SSH fallback; recorded fixtures; contract suite passes | 2 d |
| **C. SwOS driver read-only** | SNMP read + HTTP scrape backup; writable=False; SNMP-walk fixture | 1 d |
| **D. LLDP across drivers** | `_lib/lldp.py` + `get_neighbors()` per driver; recorded fixtures | 1 d |
| **E. UI integration** | platform registry, onboarding cred-step adapts, PortPanel Neighbor row, vendor UI deep-link button, About page, `isWriteLocked` hoist, README positioning copy, Playwright additions | 1–2 d |
| **F. Arista driver (read+write)** | eAPI + commit-timer; contract suite; lab fixture | 2 d |
| **G. Pica8 + FreeBSD drivers** | NETCONF confirmed-commit (write) + FreeBSD SSH (read-only) | 2–3 d |

Total: ~10–13 days for full M1 driver coverage.

## What's NOT in the architecture (and why)

- **No message bus** (RabbitMQ, Kafka, NATS) — events are intra-process; APScheduler + DB rows suffice. Adding bus = 10× ops.
- **No Redis** — cache is single-worker dict; introduce only when scaling.
- **No microservices** — one bounded context, one binary.
- **No event sourcing** — we have audit log, not event store. Don't conflate.
- **No GraphQL** — REST is enough for ~30 endpoints.
- **No service mesh, no k8s** — single VM. If we need k8s, the product failed in a different way.
- **No SSE/WebSocket v1** — polling on port_state suffices. Add WS only if "live tail" UX justifies.
- **No iframe-embedded vendor UIs** — see vendor UI deep-link section
- **No SNMP-set for writes** — half-supported across platforms; NB writes go through native APIs only
- **No multi-vendor abstraction lib (Napalm)** — <5 platforms; direct drivers clearer

## Open architecture questions

1. **Single-worker SQLite v1 — accept?** (recommend yes)
2. **Reverse proxy/TLS termination** — Tailscale-only access, nginx in front, or FastAPI directly on Tailscale-exposed port? (recommend Tailscale + nginx)
3. **Hash chain on audit log** — yes/no? (recommend yes, cheap)
4. **Drift fingerprint at request file time** — yes/no? (recommend yes)
5. **State drift on apply** — hard block or soft warn? (recommend hard block + explicit re-confirm override)
6. **Frontend served by FastAPI or separate?** (recommend FastAPI for v1)
7. **OpenAPI codegen** — types-only or full client? (recommend types-only)
8. **`puresnmp` vs `pysnmp`** — recommend puresnmp (async-native, cleaner API)
9. **SwOS lab fixture source** — real device walk vs synthetic from MIB definitions?

## Spec deviations (this doc supersedes `plan.md` where they conflict)

| `plan.md` said | New decision | Why |
|---|---|---|
| Creds in env vars per device | Encrypted in DB via CredVault | Onboarding is runtime, not config |
| Apply via APScheduler revert for FreeBSD | FreeBSD read-only forever | User policy, eliminates risk class |
| In-memory cache, no comment on multi-worker | Single-worker mandate, document split point | Prevents cache fragmentation surprises |
| Audit log just appends | Hash-chained, nightly verified | Tamper evidence, near-zero cost |
| No state machine mention | Persisted state machine + reconciler | Crash safety, trust ladder dependency |
| Stale state not addressed | Fingerprint at file, re-check at apply | Prevents stale-read clobber |
| All MikroTiks treated as RouterOS | Split: `mikrotik_routeros` (write-capable) vs `mikrotik_swos` (read-only via SNMP) | SwOS has no API; conflating breaks both drivers |
| No SNMP mentioned | SNMP is a first-class shared transport (`_lib/transport/snmp_client`) | Required for SwOS, useful for fallback across all platforms |
| No LLDP | Driver ABC exposes `get_neighbors()`; UI shows neighbor row in PortPanel | Display-only; never used for auto-discovery (PM hard NO) |
| No vendor UI escape hatch | Each driver exposes `web_ui_url_template`; UI renders "Open in vendor UI ↗" button | Keeps NB scoped; lets user escape cleanly when feature isn't covered |
