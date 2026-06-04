# Northbound

A network engineer's doctor and helper for the day-to-day port change.

## What Northbound is

Northbound is a **request-mediated port-change workflow**. Alice needs port 14 on
VLAN 200, files a request, an admin sees the rendered diff, clicks apply, and the
change ships in about 30 seconds with backup, audit, and rollback.

It targets a specific tooling gap between *observing the network* and *mass-changing
the network* — the boring everyday port move that interrupts everyone's day.

## What Northbound is NOT

Read this once and 60% of "why doesn't it do X?" questions are already answered:

- **A monitoring / alerting platform** — use LibreNMS, Observium, Prometheus + Grafana
- **A bulk config push tool** — use Ansible, MikroWizard, or Napalm
- **A network source-of-truth / intent model** — use NetBox or Nautobot
- **A multi-vendor abstraction layer** — Northbound ships direct drivers for five
  platforms (RouterOS, SwOS, Arista EOS, Pica8 PicOS, FreeBSD); Napalm is overkill
  at this scale
- **A firmware update orchestrator** — out of scope forever

Northbound **complements** those tools. Keep LibreNMS for graphs and alerts. Keep
NetBox if you have it. Run Northbound for the day-to-day port move.

When a change falls outside this scope (complex BGP, vendor-specific knobs, SwOS
writes), every device surface has an **"Open in vendor UI"** button that opens the
device's own web UI in a new tab. No dead ends.

## Architecture

One process, one VM, one SQLite file (principal-engineering D9). FastAPI serves
both the JSON API (`/api/*`) and the built React SPA (`/`) from a **single
uvicorn worker**; SQLite runs in WAL mode; config backups and the audit hash
chain live on the local filesystem. Sits behind Tailscale (or an nginx TLS
proxy). The default deployment stays single-worker SQLite; when you outgrow it,
the scale-out path is wired and supported — point `NB_DB_URL` at Postgres, set
`NB_WEB_CONCURRENCY>1`, and give slowapi a shared Redis store
(`NB_RATELIMIT_STORAGE_URI`). The background scheduler self-elects a single
leader across workers via a Postgres advisory lock, so jobs never run N times.
See **Scale out** below.

## Repository layout

- `frontend/` — Vite + React + TypeScript app (TanStack Query, Zustand, R3F)
- `src/northbound/` — Python backend (drivers, API, change pipeline)
- `seed.py` — idempotent DB seed (baseline users + optional sample devices)
- `deploy/` — systemd unit, env-file example, backup cron
- `config.example.toml` — documented configuration template
- `supporting material/` — product + engineering specs the implementation tracks

The full positioning copy lives at `/about` in the running app and in
`supporting material/pm-plan.md`.

## Quickstart (local)

```bash
# 1. Backend deps (in a venv)
python -m venv .venv && source .venv/bin/activate
make install

# 2. Dev secrets (ephemeral keys are auto-minted in development, but set these
#    so encrypted data survives restarts and login is reproducible).
export NB_SECRET_KEY=dev-secret
export NB_MASTER_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
export NB_SEED_ADMIN_PASSWORD=admin123      # else a random one is printed once

# 3. Schema + seed users (+ optional sample mock devices) + build the SPA
make migrate
make seed ARGS=--with-sample-devices
make frontend-build

# 4. Run (API + SPA on one port)
make serve                                   # http://localhost:8080
```

Open <http://localhost:8080>, log in as `admin` / `admin123`. A second user
`alice` (requester role) is also seeded.

## Configuration

Settings load with precedence **`NB_*` env vars > `northbound.toml` > defaults**.
Copy `config.example.toml` and edit, or use env vars (recommended for secrets).

| Variable | Required | Purpose |
|---|---|---|
| `NB_SECRET_KEY` | outside dev | JWT signing secret (`openssl rand -hex 32`) |
| `NB_MASTER_KEY` | outside dev | Fernet key for credential encryption at rest |
| `NB_MASTER_KEY_FILE` / `NB_SECRET_KEY_FILE` | no | Load the secret from a file (Docker/K8s/systemd secrets) instead of inline; inline wins if both set |
| `NB_DB_URL` | no | Async SQLAlchemy URL (default single-file SQLite) |
| `NB_FRONTEND_DIST` | no | Built SPA dir (default `frontend/dist`; missing → API-only) |
| `NB_ENVIRONMENT` | no | `development` (auto-mints ephemeral keys) / `production` |
| `NB_ENABLE_SCHEDULER` | no | Background jobs on/off (also gates the per-worker settings refresh) |
| `NB_WEB_CONCURRENCY` | no | uvicorn worker count (Docker entrypoint; default 1) |
| `NB_RATELIMIT_STORAGE_URI` | no | Shared rate-limit store, e.g. `redis://redis:6379/0`. **Required for correct limits when >1 worker** (else per-worker counters); needs the `.[redis]` extra |
| `NB_SCHEDULER_LOCK_RETRY_SECONDS` | no | Scheduler leader re-election cadence (default 15) |
| `NB_RUNTIME_SETTINGS_REFRESH_SECONDS` | no | How often each worker reloads admin-tuned settings from the DB (default 30) |
| `NB_SEED_ADMIN_PASSWORD` / `NB_SEED_ALICE_PASSWORD` | no | Seed passwords (else random, printed once) |

In `development`, missing `NB_SECRET_KEY`/`NB_MASTER_KEY` are auto-generated with
a loud warning; outside development they are **required** (hard startup failure).
`northbound.toml`, `config.toml`, and `.env` are gitignored — never commit real
secrets.

## Deploy (single VM)

1. `make build` — builds the SPA into `frontend/dist` (served in place).
2. Install the unit + secrets:
   ```bash
   sudo cp deploy/northbound.service /etc/systemd/system/
   sudo mkdir -p /etc/northbound /var/lib/northbound/backups
   sudo cp deploy/northbound.env.example /etc/northbound/env   # edit secrets
   sudo chmod 600 /etc/northbound/env
   sudo systemctl daemon-reload && sudo systemctl enable --now northbound
   ```
   Real secrets live in `/etc/northbound/env` (referenced via systemd
   `EnvironmentFile=`), never inline in the unit.
3. **Access:** expose port 8080 over **Tailscale** (or front it with nginx + TLS).
4. **Backups:** `deploy/backup.cron` runs a nightly `sqlite3 .backup` + `rsync`
   of `/var/lib/northbound/` (DB snapshot + config backups). Install to
   `/etc/cron.d/`.
5. `make ship` runs build + migrate locally and prints the rsync + restart steps.

### Container image — two build paths

The single SPA+API image can be built two ways:

| | Default (`Dockerfile`) | Self-contained (`Dockerfile.selfcontained`) |
|---|---|---|
| SPA build | on the **host** first, copied in | **in-image** Node stage |
| Command | `make docker-build` | `make docker-build-selfcontained` |
| Host needs | Node + npm | only Docker |
| Cost | leaner / faster | ~1–2 GB build RAM, can OOM on small hosts |

The default keeps the image lean and the host toolchain in charge. Use the
self-contained variant for host-toolchain-free builds (e.g. CI from a clean
checkout). It requires BuildKit (`DOCKER_BUILDKIT=1`, set by the make target) so
its per-Dockerfile `Dockerfile.selfcontained.dockerignore` — which keeps the
frontend sources in context — is honoured.

## Scale out (Postgres + multi-worker)

The single-worker SQLite default is fine for a lab and small fleets. To run
multiple workers (more concurrent request throughput) you need three things,
all wired and shipped:

1. **Postgres** instead of SQLite — SQLite serializes writers, so concurrent
   workers contend; Postgres tolerates them. Set
   `NB_DB_URL=postgresql+asyncpg://user:pass@host:5432/northbound`
   (the `asyncpg` driver is a base dependency — no extra install).
2. **Shared rate-limit store** — install `pip install '.[redis]'` and set
   `NB_RATELIMIT_STORAGE_URI=redis://host:6379/0`. Without it each worker keeps
   its own in-memory counters, so a `30/minute` limit becomes ~`30/minute ×
   workers`.
3. **Worker count** — `NB_WEB_CONCURRENCY=4` (read by the Docker entrypoint).

Two correctness guarantees hold automatically across workers:

- **Scheduler runs once, not N times.** Workers elect a single scheduler leader
  via a Postgres advisory lock (`services/scheduler_lease.py`); a non-leader
  takes over within `NB_SCHEDULER_LOCK_RETRY_SECONDS` if the leader dies.
- **Admin settings converge.** A runtime setting changed on one worker (e.g. the
  write rate limit) propagates to the others within
  `NB_RUNTIME_SETTINGS_REFRESH_SECONDS`.

Migrations run once before workers fork, so they never race.

The provided Compose overlay brings up Postgres + Redis + a 4-worker app:

```bash
echo "NB_PG_PASSWORD=$(openssl rand -hex 16)" >> .env
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build
```

> **Live state (SSE) caveat under multi-worker.** The SPA subscribes to
> `GET /api/events/stream` (Server-Sent Events) for live device-reachability and
> port-change updates instead of polling. Like the reachability/port-state
> caches, the event hub (`services/events.py`) is process-local: with >1 worker,
> an event reaches only the clients on the worker that produced it, so live push
> is best-effort across workers until the documented Redis pub/sub swap lands.
> Functionally harmless — clients still refetch on navigation/focus — just not
> instant for every connected tab. Single-worker (the default) is fully live.

## Live state (SSE)

While authenticated, the SPA opens one `EventSource` to `/api/events/stream`
(`useEventStream`). The browser authenticates it with the same-origin httpOnly
session cookie (EventSource cannot send an `Authorization` header) and
auto-reconnects on drop. The backend pushes two event types — `device.reachability`
(reachability poll transitions) and `device.ports` (after a write invalidates a
device's port cache) — and the client invalidates the matching TanStack queries.
No new background poller: events ride existing signals.

## Testing

```bash
make check          # ruff lint + pyright typecheck + ruff format
make test           # pytest (255 tests)
make verify         # check + test
cd frontend && npm test     # vitest unit/component
```

## Driver status

| Platform | `platform_id` | Writable | Validation |
|---|---|---|---|
| Mock (testing) | `mock` | ✓ | reference impl — full contract suite |
| Arista EOS (eAPI) | `arista` | ✓ | code-complete; fixtures **hand-authored** from vendor docs; live: **blocked** (cEOS needs arista.com auth) |
| Cisco NX-OS (NX-API) | `cisco` | ✓ | code-complete; fixtures **hand-authored**; live: **blocked** (NX-OSv licensed + KVM nesting) |
| Pica8 PicOS (NETCONF) | `pica8` | ✓ | code-complete; fixtures **hand-authored**; live: **blocked** (no public image) |
| MikroTik RouterOS / SwOS, FreeBSD | — | planned | not yet implemented |

**Honest validation stance.** The non-mock driver fixtures are **hand-authored
from vendor docs**, not captured from real hardware — so the parser and its
fixture can share the same wrong guess and still pass green (the "circular
fixture" problem). The one piece live-validated in this build is the **SSH
transport** (`asyncssh_client`), exercised against a real **FRR 9.1** node over
SSH (`sandbox/validate_ssh.py`) — the transport the FreeBSD/FRR read path uses.
Arista/Cisco/Pica8 remain behaviorally unverified until run against real
devices. The `sandbox/` rig (containerlab topology + `record_fixtures.py`
capture harness) closes this gap the moment an operator supplies a cEOS image.
Per-driver truth table: [`supporting material/vendor-docs/validation-status.md`](supporting%20material/vendor-docs/validation-status.md).
