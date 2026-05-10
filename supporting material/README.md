# Northbound — UI Prototype

Hi-fi, fully-interactive React prototype of the Northbound switch-management portal. Single-page app, mock data, no backend required. Open `Northbound.html` directly in a browser.

## What's here

```
Northbound.html          # Entry point — open this
styles.css               # Design tokens (palettes, theme, base components)
styles2.css              # Screen-specific styles (login, env picker, 3D, port panel, etc.)
theme.jsx                # ThemeProvider + palette presets + VLAN color system
data.jsx                 # Mock devices, ports, requests, audit log, users, links
ui.jsx                   # Primitives: Icon, Toast, Modal, hotkeys, Section, etc.
switch3d.jsx             # three.js 3D switch chassis + topology renderer
screens-shell.jsx        # Login, environment picker, environment view shell, sidebar, top bar
screens-device.jsx       # Device detail screen + port panel + request modal + help overlay
screens-requests.jsx     # My requests list + admin queue + diff view + config view
app.jsx                  # Root: routing, state, action handlers, NOC ribbon, tweaks panel
```

## Stack (frontend prototype only)

- React 18.3.1 (UMD) + Babel standalone (inline JSX, no build step)
- three.js 0.160 (UMD) — stylized flat-shaded 3D switch chassis & topology
- Plain CSS with oklch tokens — no Tailwind, no shadcn, no bundler

The real frontend (per the backend brief) will use Tailwind + shadcn + @react-three/fiber. This prototype intentionally avoids those so it runs as a static file. Treat it as a **visual + interaction reference**, not a code source.

## Screens implemented

1. Login (mock)
2. Environment picker (Lab / DC tiles with ambient 3D scenes)
3. Environment view (sidebar + 3D topology when no device is selected)
4. Device detail (3D switch + horizontal port strip)
5. Port detail panel (slide-in, collapsible sections)
6. Request change modal
7. My requests
8. Admin requests queue (with inline diff)
9. Device config view (read-only, syntax-highlighted, search, backup diff)
10. Help / shortcuts overlay (`?`)

## Keyboard shortcuts

- `/` focus search
- `g l` / `g d` switch to Lab / DC
- `g q` admin queue · `g r` my requests · `g h` home
- `j` / `k` previous / next port on selected device
- `r` request change on selected port
- `?` help

## Color system (key reference for the real build)

- **Palettes** are switchable (Tweaks panel): NOC Cyan, Blueprint Amber, Phosphor Tri-tone. Each defines `--nb-accent` (chrome), `--nb-link` (always link-green), background hue.
- **`--nb-link` is reserved for link-up state.** Never use it for chrome — that conflation is the #1 thing to avoid in a NOC tool.
- **VLAN colors:** named zones for canonical VLANs (mgmt 10 / storage 20 / prod 100 / voip 200 / transit 300 / guest 999), deterministic hash fallback for the rest. Same color in 3D LED stripe, 2D port card, request form, and diff view.
- **Topology links:** fiber = cyan dashed, copper = warm solid.

## Mock data

- 8 devices across Lab + DC (3× MikroTik 24-port, 1× MikroTik spine, 1× Arista 32×100G, 2× Pica8, 2× FreeBSD)
- ~280 ports with mixed up/down/disabled state
- 5 change requests in varied statuses
- 2 users: `admin`, `alice` (requester) — switch via Tweaks panel

## For the backend handoff

The shape of the change-request flow, the port description format (`VLAN-X | model | bmc_ip`), and the role split (admin vs requester) match the background doc. The mock data structure (`window.NB_DATA`) is what the API responses should look like. See `data.jsx` for the canonical shape.
