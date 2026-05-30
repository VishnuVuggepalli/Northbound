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
proxy). Scale-out split points (Redis cache → multi-worker, Postgres → >100
devices) are documented but deliberately deferred.

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
| `NB_DB_URL` | no | Async SQLAlchemy URL (default single-file SQLite) |
| `NB_FRONTEND_DIST` | no | Built SPA dir (default `frontend/dist`; missing → API-only) |
| `NB_ENVIRONMENT` | no | `development` (auto-mints ephemeral keys) / `production` |
| `NB_ENABLE_SCHEDULER` | no | Background jobs on/off |
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
| Arista EOS (eAPI) | `arista` | ✓ | fixture-backed (recorded), no live hardware here |
| Cisco | `cisco` | ✓ | fixture-backed (recorded) |
| Pica8 PicOS (NETCONF) | `pica8` | ✓ | fixture-backed (recorded) |
| MikroTik RouterOS / SwOS, FreeBSD | — | planned | not yet implemented |

No driver has been live-validated against physical hardware in this build; the
non-mock drivers run against recorded fixtures (`tests/fixtures/<platform>/`,
re-recordable via `NB_RECORD=1`).
