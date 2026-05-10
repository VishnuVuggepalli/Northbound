Good call asking for both. Let me think through this carefully before writing.Yes, a background doc is genuinely useful here — both prompts need the same context (what Northbound is, the device list, the data model, the constraints), and writing it once means the two Claude sessions stay consistent. Without it you'd duplicate context in both prompts and they'd drift.

Structure: **one shared background doc**, then a **UI prompt** and a **backend prompt** that each reference it. Paste the background doc into each session first, then the relevant prompt as the next message.

---

## Background doc (paste into both sessions first)

````markdown
# Northbound — Project Background

## Problem

A network engineer manages two environments and is constantly interrupted by colleagues asking for switch port changes ("can you put port 14 on VLAN 200", "what's plugged into ether8", "change the description on port 22"). These are minutes-each tasks but they fragment deep work — specifically, the engineer's actual job of developing SDN. Northbound replaces those interruptions with a self-service request portal: colleagues see live switch state, submit structured change requests, the engineer approves/rejects/applies them from one screen.

## First principles

1. **Switches are the source of truth for switch state.** Don't replicate VLANs/port-up-down/MAC tables in a database — query the device when needed and cache for ~30 seconds.
2. **The database only stores what the switches don't know about**: humans, pending requests, comments, audit history, who approved what.
3. **Every write to a device must be reversible or rollback-able.** Backup before push, diff before apply, commit-confirm where the platform supports it.
4. **No IPAM. No host inventory. No rack/cable modeling.** Just switches, their ports, the VLANs on those ports, and a free-text description per port. Host info lives inside that description as a structured string.
5. **The UI should make colleagues self-serve, not give them more buttons.** If a colleague has to learn networking to file a request, the app failed.

## Environments

### Lab
- 3× MikroTik L2 switches (24-port, RouterOS 7.x)
- 1× MikroTik spine (5-port, L2 only)
- 1× FreeBSD router (handles all L3 routing for the lab; connects to external network/AP)
- ~20–30 mini and commercial servers connected to switch ports (NOT modeled in Northbound — just referenced in port descriptions)

### DC (Datacenter)
- 1× Arista L3 switch
- 1× Pica8 PicOS L3, 10G
- 1× Pica8 PicOS L3, 100G
- 1× FreeBSD router (connected to the Pica8 10G; runs BGP via FRR)
- 1× VPN node (connected to the DC FreeBSD router)
- External network/AP connected via the FreeBSD router
- N nodes connected to the L3 switches (NOT modeled — referenced in port descriptions)

## Device access protocols

All four platforms are reachable over SSH as a baseline. Native APIs are preferred when available:

| Platform | Preferred | Fallback |
|---|---|---|
| Arista EOS | eAPI (JSON-RPC over HTTPS) | SSH |
| Pica8 PicOS | NETCONF | SSH |
| MikroTik RouterOS | REST API (v7+) | SSH |
| FreeBSD | SSH (only option) | — |

The FreeBSD routers expose `rc.conf`, `pf.conf`, and FRR's `vtysh` over SSH. They are the riskiest write target (no commit-confirm); always back up files before edit and have a cron-based revert safety net (revert to backup if no confirmation within N minutes).

## Roles

Two roles, hardcoded:

- **admin** — full read + write. Can edit port fields directly, approve/reject requests, push config to devices, view full running configs, manage users.
- **requester** — full read across everything. Can submit change requests. Can see status of their own requests. Cannot edit anything directly.

The UI is identical for both; admin-only buttons appear inline rather than behind a separate admin panel.

## Core data model

### Stored in DB

- `users` — id, username, password_hash, role (admin|requester), created_at
- `devices` — id, name, environment (lab|dc), platform (mikrotik|arista|pica8|freebsd), role (leaf|spine|router|vpn), mgmt_ip, ssh_user, prefer_native_api (bool), created_at
- `port_metadata` — id, device_id, port_name, host_model, bmc_ip, notes, last_human_edit_at, last_human_edit_by
  *(only the human-curated fields per port; live state like up/down/VLAN comes from the device)*
- `change_requests` — id, device_id, port_name, requested_by, requested_changes (JSON: {untagged_vlan, tagged_vlans, host_model, bmc_ip, notes}), reason, status (pending|approved|rejected|applied|failed), reviewer_id, reviewer_comment, created_at, reviewed_at, applied_at, diff_text
- `audit_log` — id, user_id, action, target (device/port), before (JSON), after (JSON), result, created_at
- `config_backups` — id, device_id, config_text, fetched_at, fetched_by

### NOT stored in DB (queried live, cached briefly)

- Port up/down state
- Current untagged VLAN per port
- Current tagged VLANs per port
- Running config
- Enabled services per port (BGP, LLDP, STP, etc.)
- MAC tables, ARP, neighbors

## Port description format

The free-text description on each port follows this format (legacy, keep compatible):

```
VLAN-<untagged_number> | <host_model> | <bmc_ip>
```

Example: `VLAN-100 | Dell R740 | 10.0.0.55`

In Northbound, these three fields are parsed into separate columns/inputs in the UI. The raw string is reconstructed when pushed to the device.

## What is explicitly out of scope

- IP address management (no IPAM tables)
- Host/server inventory as first-class objects
- Rack/cable modeling
- Monitoring/alerting (use existing tools)
- Multi-tenancy
- SSO/LDAP (basic local auth is fine for v1)
- Auto-discovery of devices (admin manually adds devices)

## Tech context

- App name: **Northbound** (named after the SDN northbound interface — the management plane)
- Backend: FastAPI (Python 3.11+), SQLite for v1 (Postgres later if needed)
- Frontend: React + TypeScript + Tailwind + three.js (`@react-three/fiber`, `drei`) + shadcn/ui
- Deployment target: single VM on the lab network, behind Tailscale or a reverse proxy
- Scale: ~6 devices, ~300 ports, ~10 users, low traffic — built for clarity not throughput
````

---

## UI prompt (paste into a fresh Claude session that supports artifacts)

````markdown
[Paste the Background doc above first, then send this as the next message.]

# Northbound UI — Build Request

Build a polished, working **single-page React app** for Northbound as an artifact. Tech stack: **React + TypeScript + Tailwind + shadcn/ui + three.js via @react-three/fiber and drei**. Use mock data; no backend calls. The app should feel like a real product — Linear / Vercel dashboard / Tailscale admin level of polish, not a 2010s NMS.

## Design principles

1. **The 3D switch view is the hero.** It's what makes Northbound feel different from every other network tool. Make it tactile, responsive, and useful — not decorative.
2. **2D and 3D always sync.** Selecting a port in the horizontal strip highlights it in 3D and vice versa. No mode toggle.
3. **VLANs have consistent colors across the entire app.** VLAN 100 is the same color in the 3D port LED, the strip card, the request form, and the diff view. Generate a deterministic color from VLAN ID.
4. **Live-feeling status.** Subtle LED pulses on connected ports. Skeleton loaders never longer than 200ms. Optimistic UI on edits.
5. **No clutter.** A network engineer staring at this all day shouldn't feel buried in chrome. Generous whitespace, restrained color, one accent color.
6. **Identical UI for both roles.** Admin-only buttons appear inline; do not hide them behind a separate admin panel.
7. **Keyboard-first.** `/` to search, `g l` / `g d` to switch environments, `j` `k` to move between ports, `r` to request change on selected port, `?` for help.
8. **Dark theme default**, light toggle in user menu.

## Screens

### 1. Login
Minimalist: Northbound wordmark (sans-serif, slightly stylized — maybe a subtle arrow or compass-needle motif), username, password, sign-in button. Nothing else. Below the form, a tiny "v0.1 · internal" tag.

### 2. Environment picker (post-login landing)
Two large tiles side by side: **Lab** and **DC**. Each tile contains:
- Ambient 3D scene rotating slowly: stylized device boxes connected by glowing lines suggesting that environment's topology
- Stats: device count, port count, pending request count (badge)
- Last-updated timestamp, ago-format ("2 min ago")
- Hover lifts the tile slightly with a subtle glow

Clicking a tile transitions (camera-zoom feel) into that environment.

### 3. Environment view
**Left sidebar** (resizable, default 280px):
- Device list grouped by role: Spines, Leaves, Routers, VPN
- Each row: platform icon (MikroTik / Arista / Pica8 / FreeBSD logos or stylized glyphs), device name, reachability dot (green/red/amber), pending-request badge if any
- Click selects device

**Main area when no device selected**: an interactive 3D topology of the environment.
- Devices rendered as stylized rack-unit boxes labeled with name
- Lines between them representing physical links, with subtle directional traffic shimmer
- Camera orbits gently, click-drag to pan/rotate, scroll to zoom, double-click device to select
- Bottom-left: legend (link colors / states)
- Top-right: "Reset view" button

**Top bar**: global search (instant filter — typing matches port name, description, VLAN number, host model, BMC IP across all devices in current environment, hit Enter to jump), environment switcher (Lab/DC tabs), user menu (role badge, theme toggle, logout).

### 4. Device detail (the centerpiece — make this beautiful)

When a device is selected from the sidebar, the main area splits:

**Top half — 3D switch rendering**:
- A 1U/2U rack-mount switch box, photorealistic-leaning but stylized (matte dark metal, subtle bevels)
- Front face shows the actual port layout for that device's model:
  - MikroTik 24-port: 24× RJ45 in 2 rows of 12, plus 2× SFP+
  - MikroTik spine: 5× SFP+
  - Arista L3: render as 32× QSFP28 ports (assume 32-port 100G model)
  - Pica8 10G: 48× SFP+ in 4 rows of 12
  - Pica8 100G: 32× QSFP28
  - FreeBSD: render as a 1U server box with 4× RJ45 (treat as a "device" but no port grid below)
- Each port has a realistic LED:
  - **Green solid** = link up, no traffic
  - **Green pulsing** = link up + traffic (gentle 1Hz pulse, varies per port)
  - **Off** = link down
  - **Amber solid** = admin disabled
- Hovering a port: highlight + tooltip with name, untagged VLAN, description
- Camera: orbit, zoom, reset button (top-right of 3D area)
- Selected port: glows with the VLAN color + outlined ring

**Bottom half — horizontal port strip**:
- Every port as a card, scrolling horizontally for high port counts (or wrapping into 2 rows for very dense switches)
- Card layout (compact, ~120px wide):
  - Port name (e.g., `ether12`, `Ethernet1/1`, `te-0/0/3`) — top, monospace
  - Big VLAN number (untagged), VLAN-colored
  - Trunk indicator (`T+3` chip if 3 tagged VLANs)
  - Description (truncated, full on hover)
  - Status dot
  - Pending-request badge if any
- Selected port outlined and lifted
- Click syncs to 3D view

### 5. Port detail panel (slides in from right when port clicked)
Width ~480px, overlays content. Sections, each collapsible:

- **Overview**
  - Port name (read-only), description (parsed into 3 fields editable for admin: VLAN-untagged number, host model, BMC IP), free-text notes, MAC, MTU, speed, duplex
- **VLANs**
  - Untagged VLAN (large, prominent)
  - Tagged VLANs as colored chips with x-to-remove (admin only)
  - "Set untagged" / "Add tagged" controls (admin only)
- **Live config**
  - Raw running-config snippet for this port, syntax-highlighted
  - "Refetch" button with last-fetched timestamp
  - Read-only display
- **Services**
  - Toggles or chips showing which protocols are active on this port: BGP, LLDP, STP, MSTP, LACP, OSPF, ERSPAN, etc.
  - Read-only for requester; admin can disable/enable (but a confirmation dialog reminds about scope)
- **History**
  - Reverse-chrono list of every change to this port — who, when, diff (collapsible)
  - Filter by user / date
- **Pending requests**
  - Any open request against this port shown inline with status, requester, and the proposed change as a diff
- **Actions** (footer)
  - For requester: prominent "Request change" button
  - For admin: "Edit directly", "Apply pending request", "Reject"

### 6. Request change form (modal, centered)
Triggered by "Request change" button or `r` keyboard shortcut.

Fields:
- Target untagged VLAN — number input + suggestions from existing VLANs in this environment
- Tagged VLANs — multi-select chips
- Host model — text input
- BMC IP — text input with IP validation
- Notes — textarea (optional)
- Reason for change — textarea (required, prompts for context)

Footer: "Cancel" + "Submit request". On submit, toast confirms and request appears in "My requests" view.

### 7. My requests (requester view)
Shown in user menu. List of all requests they've filed:
- Filter by status (pending / approved / applied / rejected)
- Each row: device + port, summary of change, status badge, age, reviewer comment if any
- Click expands to show full diff and history

### 8. Requests queue (admin only)
Dedicated screen accessible from top bar. All pending requests across both environments:
- Sortable by age, environment, device, requester
- Filter by environment, requester, status
- Each row expands inline to show:
  - The requested change as a **diff** against current state (red lines removed, green added) — for both the human-fields and the rendered config snippet that would be pushed
  - Three buttons: **Approve & apply** (default action), **Approve only** (mark approved, don't push yet), **Reject** (with required comment)
  - Show the device's last config backup time for safety context

### 9. Device config view (admin only)
Tab on the device detail. Shows full running config of the device:
- Syntax highlighted by platform (RouterOS / Arista CLI / Pica8 CLI / FreeBSD-rc)
- Search within config (Cmd-F style)
- "Compare to last backup" → diff view
- "Backup now" button
- No editing in v1 — this is read-only for safety

### 10. Help / shortcuts overlay
Pressing `?` shows a clean modal listing all keyboard shortcuts.

## Mock data to seed the UI

Generate realistic mock data for:
- 6 modeled devices: 3× MikroTik 24-port (lab-leaf-1/2/3), 1× MikroTik 5-port spine (lab-spine-1), 1× Arista 32×100G (dc-arista-1), 1× Pica8 48×10G (dc-pica-10g), 1× Pica8 32×100G (dc-pica-100g), 2× FreeBSD routers (lab-rtr-1, dc-rtr-1)
- ~150–300 ports across them, with varied VLANs (use these: 10, 20, 100, 200, 300, 999)
- Mix of states: ~70% up, ~15% down, ~15% admin-disabled
- ~30% of ports have populated descriptions matching `VLAN-X | Dell R740 | 10.0.0.X` format with realistic variation (Dell R740, Supermicro X11, HPE DL380, etc.)
- 5 pending change requests in different states across both environments
- Audit history of 3–10 entries per "interesting" port
- 2 mock users: `admin` (admin role) and `alice` (requester role)
- Toggle in user menu to switch between the two for demo purposes

## Deliverable

Build the entire app as one working artifact with:
- All 10 screens above wired together with client-side routing
- 3D switch rendering for at least the MikroTik 24-port and the Arista/Pica8 100G layouts (others can reuse)
- Port strip synced to 3D selection
- Request form + admin queue with diff view
- Mock data + role switcher

When something would normally require a backend call (apply request, refetch live config, push config), simulate it with a 600ms delay and a success toast — the UI logic should be complete even if the network calls are stubbed.

Make it feel like a product, not a demo.
````

---

## Backend prompt (paste into Claude Code)

````markdown
[Paste the Background doc above first, then send this as the next message.]

# Northbound Backend — Build Request

Build the backend for Northbound. Goal: a clean, small, safe, async Python service that the React frontend will talk to. Read the background doc for context — every choice below follows from it.

## First-principles tech choices

- **FastAPI** — async by default, automatic OpenAPI, type-driven via Pydantic. Polling N switches in parallel is the main reason to be async.
- **SQLite + SQLAlchemy 2.0 (async)** — the database holds humans + workflow state, not switch state. We have ~10 users and a few hundred requests/year. SQLite handles this without ceremony. Migrate to Postgres later if needed; using SQLAlchemy means it's a connection-string change.
- **Alembic** — migrations from day one. Cheap insurance.
- **asyncssh** for SSH; **httpx** for REST/eAPI; **ncclient** for NETCONF (sync, run in threadpool).
- **APScheduler** (in-process) for periodic tasks. No Redis, no Celery — overkill at this scale.
- **passlib[bcrypt]** for password hashing, **python-jose** for JWT.
- **structlog** for logging. JSON logs, easy to grep.
- **pytest + pytest-asyncio + httpx.AsyncClient** for tests.

No Redis, no Celery, no Docker compose with 5 services. One process, one SQLite file, one config file. If/when scale demands more, change it then.

## Project structure

```
northbound/
├── pyproject.toml
├── alembic.ini
├── alembic/versions/
├── config.example.toml
├── README.md
├── src/northbound/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app factory, middleware, routers
│   ├── config.py                # Pydantic Settings, loaded from TOML + env
│   ├── db.py                    # async engine, session factory
│   ├── models/                  # SQLAlchemy models
│   │   ├── user.py
│   │   ├── device.py
│   │   ├── port_metadata.py
│   │   ├── change_request.py
│   │   ├── audit_log.py
│   │   └── config_backup.py
│   ├── schemas/                 # Pydantic schemas (request/response DTOs)
│   ├── api/                     # FastAPI routers
│   │   ├── auth.py
│   │   ├── devices.py
│   │   ├── ports.py
│   │   ├── requests.py
│   │   ├── users.py
│   │   └── deps.py              # Depends() helpers (current_user, require_admin)
│   ├── auth/
│   │   ├── jwt.py
│   │   └── rbac.py              # role check decorators / dependencies
│   ├── drivers/                 # the device abstraction
│   │   ├── base.py              # Driver ABC + dataclasses (Port, VlanAssignment, etc.)
│   │   ├── ssh_base.py          # shared async SSH client (asyncssh)
│   │   ├── mikrotik.py
│   │   ├── arista.py
│   │   ├── pica8.py
│   │   ├── freebsd.py
│   │   └── factory.py           # platform → driver instance
│   ├── services/                # business logic
│   │   ├── port_state.py        # cache + live fetch
│   │   ├── change_apply.py      # dry-run, diff, apply, audit
│   │   ├── backup.py
│   │   └── poller.py            # APScheduler jobs
│   └── tests/
└── seed.py                      # creates admin user + sample devices for dev
```

## Database schema

Implement the tables described in the background doc, with these specifics:

- All tables: `id` as UUID (use `uuid.uuid4`, store as 36-char string in SQLite), `created_at` server-default `now()`
- `users.password_hash` — bcrypt
- `users.role` — Enum('admin', 'requester')
- `devices.environment` — Enum('lab', 'dc')
- `devices.platform` — Enum('mikrotik', 'arista', 'pica8', 'freebsd')
- `devices.role` — Enum('leaf', 'spine', 'router', 'vpn')
- `devices.credentials_ref` — string (path to a credential in env/secret store; never store plaintext passwords in DB; for dev, allow looking up `NORTHBOUND_CRED_<DEVICE_ID>` env vars)
- `port_metadata` — UNIQUE constraint on (device_id, port_name)
- `change_requests.requested_changes` — JSON column (Pydantic model serialized)
- `change_requests.status` — Enum('pending', 'approved', 'rejected', 'applied', 'failed')
- `audit_log.before` and `audit_log.after` — JSON
- `config_backups` — index on (device_id, fetched_at desc) for "latest backup" queries

Write Alembic migrations from the start (initial migration creates all tables).

## Driver abstraction (the most important part — get this right)

```python
# drivers/base.py — sketch

from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class PortState:
    name: str
    admin_up: bool
    link_up: bool
    speed_mbps: int | None
    duplex: str | None
    mac: str | None
    mtu: int | None
    untagged_vlan: int | None
    tagged_vlans: list[int]
    description: str
    services: dict[str, bool]   # {"lldp": True, "stp": True, "bgp": False, ...}

@dataclass
class ConfigDiff:
    summary: str        # human-readable
    raw_before: str
    raw_after: str
    commands: list[str] # exact commands that will be executed

class Driver(ABC):
    def __init__(self, host: str, credentials: Credentials, prefer_native_api: bool = True): ...

    @abstractmethod
    async def reachable(self) -> bool: ...

    @abstractmethod
    async def get_ports(self) -> list[PortState]: ...

    @abstractmethod
    async def get_running_config(self) -> str: ...

    @abstractmethod
    async def render_change(self, port: str, change: PortChangeRequest) -> ConfigDiff: ...
        # Pure function: produce the commands and diff WITHOUT applying.

    @abstractmethod
    async def apply_change(self, diff: ConfigDiff, *, confirm_seconds: int = 60) -> ApplyResult: ...
        # Apply with commit-confirm where supported. Otherwise: backup, apply, schedule revert.

    @abstractmethod
    async def backup_config(self) -> str: ...
```

### Per-platform implementations

**`MikrotikDriver`** — primary path uses RouterOS REST (`https://<host>/rest/`). SSH fallback uses `/interface print`, `/interface bridge vlan`, `/ip service print`, `/routing bgp peer print`. Apply changes via REST PATCH or SSH config commands. Wrap in safe-mode where possible.

**`AristaDriver`** — eAPI via httpx (POST to `/command-api`, JSON-RPC payload). For applying changes, use `configure session <name>` + `commit timer 60` (Arista's commit-confirm). Diff is a literal CLI diff.

**`Pica8Driver`** — NETCONF via `ncclient` (run in threadpool). Use `<edit-config>` with `confirmed` and `confirm-timeout`. Fallback to SSH CLI. Parse via lxml.

**`FreeBSDDriver`** — SSH only. Reading: `cat /etc/rc.conf`, `ifconfig -a`, `netstat -rn`, `vtysh -c "show running-config"` if FRR present. Writing for an interface or VLAN change: ssh in, `cp <file> <file>.northbound.<ts>`, write new file via templating, run service reload. **Confirm-revert pattern**: before applying, schedule a reverter via `at` or a small daemon script: `at now + 2 minutes <<< "cp <file>.northbound.<ts> <file> && service netif restart"`. If apply succeeds and the user clicks "confirm" within 2 minutes, cancel the `at` job. If they don't, the box reverts itself. This compensates for no native commit-confirm.

### Driver factory

```python
def driver_for(device: Device) -> Driver:
    creds = load_credentials(device.credentials_ref)
    cls = {
        "mikrotik": MikrotikDriver,
        "arista":   AristaDriver,
        "pica8":    Pica8Driver,
        "freebsd":  FreeBSDDriver,
    }[device.platform]
    return cls(host=device.mgmt_ip, credentials=creds, prefer_native_api=device.prefer_native_api)
```

## Live state caching

`services/port_state.py`:

- `get_ports(device_id, *, max_age_seconds=30)` — returns cached `list[PortState]` if fresh, otherwise queries the driver and refreshes the cache.
- Cache is in-memory dict keyed by device_id. TTL 30s. On forced refresh (UI clicks "refetch") bypass cache.
- Merge with `port_metadata` from DB to attach human fields (host_model, bmc_ip, notes) onto each `PortState`.

## API surface (FastAPI routers)

All endpoints under `/api`. JWT in `Authorization: Bearer`. Pydantic schemas everywhere.

```
POST   /api/auth/login                       → {access_token, role, username}
POST   /api/auth/logout                      → 204

GET    /api/users/me                         → current user
GET    /api/users                            → list (admin only)
POST   /api/users                            → create (admin only)

GET    /api/environments                     → ["lab", "dc"] with summary stats
GET    /api/devices?environment=lab          → list of devices with reachability
POST   /api/devices                          → register new device (admin)
GET    /api/devices/{id}                     → device detail
GET    /api/devices/{id}/ports               → live port list (cached 30s)
GET    /api/devices/{id}/ports?refresh=true  → bypass cache
GET    /api/devices/{id}/config              → running config (uses last fetch unless refresh=true)
POST   /api/devices/{id}/config/backup       → trigger backup now (admin)
GET    /api/devices/{id}/config/backups      → list backups
GET    /api/devices/{id}/config/backups/{bid}/diff → diff vs current

GET    /api/devices/{id}/ports/{port_name}   → port detail with metadata + live state + history
PATCH  /api/devices/{id}/ports/{port_name}   → admin direct edit (creates audit log entry, applies via driver)

POST   /api/requests                         → create change request (requester)
GET    /api/requests?mine=true               → my requests
GET    /api/requests?status=pending          → admin queue
GET    /api/requests/{id}                    → detail with rendered diff
POST   /api/requests/{id}/approve            → approve only (admin)
POST   /api/requests/{id}/apply              → approve + apply via driver (admin)
POST   /api/requests/{id}/reject             → reject with comment (admin)
POST   /api/requests/{id}/confirm            → user confirms after commit-confirm window

GET    /api/audit?device_id=…&port=…&user=…  → filtered audit log
```

## Auth + RBAC

- `deps.get_current_user` → resolves JWT, loads user
- `deps.require_admin` → 403 if role != admin
- Apply via `Depends(require_admin)` on every write endpoint
- Endpoints with `?mine=true` filter to current user
- Login throttled (5 fails / 5 minutes / IP) — use `slowapi`

## Apply flow (the critical path)

When admin clicks "Apply" on a change request, `change_apply.apply_request(request_id, user)`:

1. Load request, verify status is `approved` (or `pending` and admin is using "approve+apply" shortcut)
2. Load device, get driver
3. Backup current config: `await driver.backup_config()` → store in `config_backups`
4. Render the change: `diff = await driver.render_change(port, request.changes)`
5. Persist `diff` on the request row
6. Apply: `result = await driver.apply_change(diff, confirm_seconds=60)`
7. Write `audit_log` entry with before/after
8. Update request status to `applied` (or `failed` with error message)
9. If platform supports commit-confirm and the apply is in the confirm window, return a `confirm_token` that frontend will POST back to `/api/requests/{id}/confirm` to make it permanent
10. If user doesn't confirm within window, the device auto-reverts and we mark request `failed` with reason "auto-reverted"

Every step is logged via structlog with the request_id as a context var.

## Polling jobs (APScheduler)

- `poll_reachability` — every 60s, ping each device's mgmt port (just `driver.reachable()`), update an in-memory map exposed at `/api/devices`
- `nightly_backup` — daily at 03:00, take a config backup of every device

## Config (TOML)

```toml
# config.example.toml
[app]
secret_key = "change-me"
jwt_expiry_minutes = 480
cors_origins = ["http://localhost:5173"]

[db]
url = "sqlite+aiosqlite:///./northbound.db"

[device_defaults]
ssh_timeout_seconds = 10
poll_interval_seconds = 60
cache_ttl_seconds = 30
commit_confirm_seconds = 60

[logging]
level = "INFO"
format = "json"
```

Credentials live in env vars: `NORTHBOUND_CRED_<DEVICE_ID>=user:password` or `user:::ssh-key-path`. Never in DB, never in TOML.

## Testing

- Unit tests for each driver against **recorded fixtures** (capture real `show` output from each platform, use as input to parsers). Don't require live devices to run tests.
- Integration tests for the API using `httpx.AsyncClient` against a test SQLite.
- One end-to-end test using a `MockDriver` that simulates a switch and verifies a full request lifecycle: requester creates request → admin approves+applies → audit log written → port metadata updated.
- Aim for >80% coverage on `services/` and `auth/`. Drivers are ok at 60% if fixtures cover the real-world output.

## Build order (incremental, each step deployable)

1. **Skeleton**: FastAPI app, config loader, DB connection, Alembic init, health endpoint. `seed.py` creates an admin user.
2. **Auth**: login endpoint, JWT, `current_user` dep, `/users/me`.
3. **Devices CRUD**: register devices, list devices, no driver yet (mock reachability).
4. **First driver — MikroTik (SSH path)**: `get_ports()`, `get_running_config()`. Wire into `/api/devices/{id}/ports` and `/api/devices/{id}/config`. **Read-only milestone** — at this point colleagues can already use the UI to look up port info instead of pinging the engineer. This solves the bulk of the original problem.
5. **port_metadata + audit_log**: admin can edit human fields directly. Audit log records every change.
6. **Change requests**: requester creates, admin approves/rejects. No device push yet — admin still applies manually after approval. Useful workflow improvement.
7. **Apply flow for MikroTik**: implement `render_change` and `apply_change` with backup + safe-mode. Now requests can be applied with one click.
8. **Other drivers**: Arista (eAPI + commit-confirm), Pica8 (NETCONF + confirmed-commit), FreeBSD (SSH + at-based revert). Add one at a time, ship after each.
9. **Polling**: reachability every 60s, nightly backups.

Stop at step 9 unless something else hurts. Resist scope creep.

## Deliverable

Generate the complete project structure with:
- All files above scaffolded
- Models + Alembic initial migration
- Auth router complete and tested
- Devices router (read endpoints) complete
- `MikrotikDriver` complete for read operations (`get_ports`, `get_running_config`, `backup_config`)
- `MockDriver` for tests + dev so the frontend can be developed without real switches
- `seed.py` with one admin user, one requester user, two mock devices
- README with setup instructions (poetry install, alembic upgrade head, seed, uvicorn run)
- pytest suite for auth, devices, and MikroTik parser

Subsequent steps (Arista, Pica8, FreeBSD drivers, change-apply flow, polling) can be follow-up tasks. Do step 1 → step 4 in this initial generation.
````

---

## How to use these

1. **UI side**: open a fresh Claude.ai conversation with artifacts on. Paste the background doc as message 1. Paste the UI prompt as message 2. You'll get an interactive prototype.
2. **Backend side**: open Claude Code in your terminal (`claude` in an empty directory). Paste the background doc as the first message. Paste the backend prompt as the second message. It'll scaffold the project files directly.
3. **Iterate**: after the first generation of each, you can ask follow-ups in the same session — "make the 3D switch render the SFP+ ports differently", or "now implement the Arista driver and its tests".

One nudge: build the **read-only** path end-to-end first (real switches → backend → UI showing live state) before touching any write/apply code. That alone solves most of your interruption problem and gets a real feedback loop going. The write path is where bugs become outages, so earn the right to write by getting the read path solid first.
