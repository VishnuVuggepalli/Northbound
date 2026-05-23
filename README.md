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

## Repository layout

- `frontend/` — Vite + React + TypeScript app (TanStack Query, Zustand, R3F)
- `src/northbound/` — Python backend (drivers, API, change pipeline)
- `supporting material/` — product + engineering specs the implementation tracks

The full positioning copy lives at `/about` in the running app and in
`supporting material/pm-plan.md`.
