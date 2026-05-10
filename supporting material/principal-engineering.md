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
    max_concurrency: int
    auth_kinds: list[Literal["password", "ssh_key", "api_token"]]

class Driver(ABC):
    capabilities: ClassVar[DriverCapabilities]
    platform_id: ClassVar[str]   # registry key

    def __init__(self, conn: ConnectionParams, creds: Credentials): ...

    # onboarding
    async def test_credentials(self) -> TestResult: ...
    async def discover(self) -> DiscoveryResult: ...

    # read
    async def reachable(self) -> bool: ...
    async def get_ports(self) -> list[PortState]: ...
    async def get_running_config(self) -> str: ...
    async def backup_config(self) -> str: ...

    # write — raise NotSupported if writable=False
    async def render_change(self, port: str, change: PortChange) -> ConfigDiff: ...
    async def apply_change(self, diff: ConfigDiff, *, confirm_seconds: int) -> ApplyResult: ...
    async def confirm(self, apply_token: str) -> None: ...
    async def revert(self, apply_token: str) -> None: ...
```

New platform = subclass + registry entry. Wizard, API, UI all use it generically.

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

## What's NOT in the architecture (and why)

- **No message bus** (RabbitMQ, Kafka, NATS) — events are intra-process; APScheduler + DB rows suffice. Adding bus = 10× ops.
- **No Redis** — cache is single-worker dict; introduce only when scaling.
- **No microservices** — one bounded context, one binary.
- **No event sourcing** — we have audit log, not event store. Don't conflate.
- **No GraphQL** — REST is enough for ~30 endpoints.
- **No service mesh, no k8s** — single VM. If we need k8s, the product failed in a different way.
- **No SSE/WebSocket v1** — polling on port_state suffices. Add WS only if "live tail" UX justifies.

## Open architecture questions

1. **Single-worker SQLite v1 — accept?** (recommend yes)
2. **Reverse proxy/TLS termination** — Tailscale-only access, nginx in front, or FastAPI directly on Tailscale-exposed port? (recommend Tailscale + nginx)
3. **Hash chain on audit log** — yes/no? (recommend yes, cheap)
4. **Drift fingerprint at request file time** — yes/no? (recommend yes)
5. **State drift on apply** — hard block or soft warn? (recommend hard block + explicit re-confirm override)
6. **Frontend served by FastAPI or separate?** (recommend FastAPI for v1)
7. **OpenAPI codegen** — types-only or full client? (recommend types-only)

## Spec deviations (this doc supersedes `plan.md` where they conflict)

| `plan.md` said | New decision | Why |
|---|---|---|
| Creds in env vars per device | Encrypted in DB via CredVault | Onboarding is runtime, not config |
| Apply via APScheduler revert for FreeBSD | FreeBSD read-only forever | User policy, eliminates risk class |
| In-memory cache, no comment on multi-worker | Single-worker mandate, document split point | Prevents cache fragmentation surprises |
| Audit log just appends | Hash-chained, nightly verified | Tamper evidence, near-zero cost |
| No state machine mention | Persisted state machine + reconciler | Crash safety, trust ladder dependency |
| Stale state not addressed | Fingerprint at file, re-check at apply | Prevents stale-read clobber |
