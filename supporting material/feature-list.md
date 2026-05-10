# Northbound — Feature List

> Companion to `plan.md`, `pm-plan.md`, `principal-engineering.md`.
> Consolidated feature inventory with milestone tiers.

## Tier key

| Tier | Milestone | When |
|---|---|---|
| **A** | M1 — Read directory + onboarding | wk 2 |
| **B** | M2 — Request workflow, manual apply | wk 4 |
| **C** | M3 — One-click apply (lab MikroTik) | wk 6 |
| **D** | M4 — DC drivers (Arista, Pica8) | wk 10 |
| **E** | M5 — Polling + nightly backup | wk 11 |
| **L** | Later / deferred | — |
| **N** | Never (anti-feature) | — |

## Two tracks

- **Track 1 (primary):** switches backend + UI. Tiers A–E.
- **Track 2 (secondary):** Cliq + Zoho Mail. Starts only after Track 1 M1 ships.

---

## Auth & users

| # | Feature | Tier |
|---|---|---|
| F1 | Local login (username + bcrypt password) | A |
| F2 | JWT bearer auth | A |
| F3 | Two roles: admin, requester | A |
| F4 | `/users/me`, admin user CRUD | A |
| F5 | Login throttle (5 fails / 5min / IP) | A |
| F6 | User profile: email, Zoho user_id link | B |
| F7 | Zoho SSO | N |
| F8 | LDAP/OIDC | N |

## Devices & onboarding

| # | Feature | Tier |
|---|---|---|
| F10 | Device registry (CRUD via UI, admin only) | A |
| F11 | Driver registry + plugin shape | A |
| F12 | `GET /platforms` (registry list with capabilities) | A |
| F13 | Onboarding wizard backend (test → discover → atomic save) | A |
| F14 | Onboarding wizard UI (7 steps) | A |
| F15 | Encrypted creds at rest (CredVault interface, Fernet impl) | A |
| F16 | Master key from env (`NB_MASTER_KEY`) | A |
| F17 | Credential rotation flow | B |
| F18 | Re-discover endpoint | B |
| F19 | Preview mode (one-shot creds, nothing stored) | A (recommended) |
| F20 | Reachability stub at onboard, real polling later | A → E |
| F21 | Hard read-only lock on `role in (router, vpn)` | A |
| F22 | Auto-discovery (subnet scan) | N |
| F23 | Bulk CSV device import | N |

## Ports — read

| # | Feature | Tier |
|---|---|---|
| F30 | Live port list per device (cached 30s) | A |
| F31 | Force refresh (`?refresh=true`) | A |
| F32 | Port state: admin_up, link_up, speed, duplex, MAC, MTU | A |
| F33 | VLAN: untagged + tagged list | A |
| F34 | Description parse `VLAN-X \| model \| bmc_ip` → 3 fields | A |
| F35 | Active services per port (LLDP, STP, BGP, etc.) | A |
| F36 | Global search across env (port name, desc, VLAN, model, BMC IP) | A |
| F37 | Port history (audit log filtered) | B |
| F38 | MAC/ARP/neighbor tables | L |

## Ports — write (admin direct edit)

| # | Feature | Tier |
|---|---|---|
| F40 | `PATCH /ports/{name}` admin direct edit (metadata only) | B |
| F41 | Admin direct VLAN change (writable platforms) | C |
| F42 | Admin direct enable/disable port | C |
| F43 | Bulk port operations | N |

## Change requests

| # | Feature | Tier |
|---|---|---|
| F50 | Requester files request (untagged VLAN, tagged, model, BMC, notes, reason) | B |
| F51 | Status state machine: pending → approved/rejected → applied/failed | B |
| F52 | My requests list | B |
| F53 | Admin queue (pending across all envs) | B |
| F54 | Diff view (current vs requested, both fields + rendered config) | B |
| F55 | Approve only (no apply) | B |
| F56 | Reject with required comment | B |
| F57 | Approve + apply (one click) | C |
| F58 | Stale-state guard: re-fetch device state at apply, reject if drift | C |
| F59 | Confirm endpoint for commit-confirm window | C |
| F60 | Reject if target device role in (router, vpn) at create | B |
| F61 | Scheduled requests ("apply at 2am") | N |
| F62 | Bulk requests | N |
| F63 | Request templates | L |
| F64 | Request comment thread | N (use Cliq) |

## Apply flow (per platform)

| # | Feature | Tier |
|---|---|---|
| F70 | MikroTik apply (REST primary, SSH fallback, safe-mode) | C |
| F71 | Arista apply (eAPI + `commit timer 60`) | D |
| F72 | Pica8 apply (NETCONF confirmed-commit) | D |
| F73 | FreeBSD apply | N (read-only forever) |
| F74 | Backup-before-push (mandatory) | C |
| F75 | Render-change dry-run (returns diff, no push) | C |
| F76 | Auto-revert on failed confirm (where supported) | C |
| F77 | Per-device feature flag (gradual rollout) | C |
| F78 | Persisted state machine + reconciler loop | C |

## Audit & backups

| # | Feature | Tier |
|---|---|---|
| F80 | Audit log: every write, before/after JSON | B |
| F81 | Audit log hash chain (tamper evidence) | B |
| F82 | Audit query API (filter by device, port, user, date) | B |
| F83 | Config backup table | A |
| F84 | On-demand backup (admin) | A |
| F85 | Nightly backup (all devices, 03:00) | E |
| F86 | Backup diff (current vs backup N) | A |
| F87 | Blocked-write attempts logged (`write.denied`) | B |

## Background jobs (APScheduler in-process)

| # | Feature | Tier |
|---|---|---|
| F90 | Reachability poll (60s) | E |
| F91 | Nightly backup (03:00) | E |
| F92 | Reconciler loop (10s, applies/confirms) | C |
| F93 | Audit hash chain verifier (nightly) | B |
| F94 | Inbound email poll (60s) | C (Track 2) |
| F95 | Token refresh (Zoho OAuth) | B (Track 2) |

## Track 2 — Cliq integration

| # | Feature | Tier |
|---|---|---|
| F100 | `/nb port <device> <port>` lookup | A (stretch) |
| F101 | `/nb device <device>` summary | A (stretch) |
| F102 | `/nb requests` mine pending | B |
| F103 | `/nb help` | A (stretch) |
| F104 | Bot DM admin on request created (with diff preview + buttons) | B |
| F105 | Interactive [Approve & Apply] [Approve only] [Reject] | B (approve), C (apply) |
| F106 | `#northbound` channel notifications (applied, unreachable) | B |
| F107 | Daily digest to admin (9am) | B |
| F108 | HMAC webhook verify (inbound from Cliq) | B |
| F109 | User Zoho-NB identity link prompt on first command | B |
| F110 | DM redirect snippet (`/nb-tip`) | A (stretch) |
| F111 | Auto-listen on admin's DMs | N (creepy) |

## Track 2 — Zoho Mail integration

| # | Feature | Tier |
|---|---|---|
| F120 | Outbound: request applied receipt to requester | B |
| F121 | Outbound: failure alert to requester + admin | B |
| F122 | Outbound: daily digest to admin | B |
| F123 | Inbound: parse `[NB] device port -> VLAN N` template → request | C |
| F124 | Inbound: sender allowlist (`users.email` + DKIM-pass) | C |
| F125 | Inbound: reply with parse error or portal link | C |
| F126 | LLM fallback parser for free-form emails | L |
| F127 | Real-time per-event email to admin | N (Cliq does it) |

## Track 2 — Zoho Projects

| # | Feature | Tier |
|---|---|---|
| F130 | Mirror NB request → Zoho task (one-way) | L |
| F131 | Two-way sync | N |

## Cross-cutting

| # | Feature | Tier |
|---|---|---|
| F140 | Pydantic Settings from TOML + env | A |
| F141 | structlog JSON logs | A |
| F142 | Request-id contextvar on every log line | A |
| F143 | Cred redaction at log layer | A |
| F144 | Alembic migrations from day 1 | A |
| F145 | Per-driver recorded fixtures (test without live device) | A |
| F146 | MockDriver (frontend unblocker, e2e tests) | A |
| F147 | Health endpoint | A |
| F148 | OpenAPI docs at `/docs` | A |
| F149 | OpenAPI types codegen for frontend | A |
| F150 | Versioned API (`Accept` header) | A |
| F151 | Rate limit on write endpoints | B |
| F152 | Per-device feature flags table | C |
| F153 | Encrypt-at-rest beyond creds (e.g. tokens) | L |
| F154 | Production secret store (Vault/SOPS) | L |
| F155 | Postgres migration (when SQLite hurts) | L |
| F156 | Multi-worker + Redis cache | L |
| F157 | SSE/WebSocket for live state | L |

## Anti-features (hard NO)

- IPAM, host inventory, rack/cable modeling
- Monitoring/alerting (use existing tools)
- Multi-tenancy
- Auto-discovery (subnet scan)
- Mobile app
- External public REST API / webhooks
- Analytics dashboard
- Bulk operations (one device, one port at a time)
- Scheduled changes
- **FreeBSD writes** (forever)
- Two-way Zoho Projects sync
- In-app comment threads (Cliq exists)
- Bulk CSV device import
- Pre-shipped vendor configs
- Auto-listen DM bot

## Counts (rough)

| Tier | Count |
|---|---|
| A (M1) | 30 |
| B (M2) | 26 |
| C (M3) | 14 |
| D (M4) | 2 |
| E (M5) | 3 |
| L (later) | 9 |
| N (never) | 18 |
