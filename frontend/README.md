# Northbound — frontend

Production frontend for Northbound, the switch-management portal. It talks to a
real FastAPI backend, with a fully offline mock client kept behind a flag so dev
and Playwright E2E run without a server.

- `src/api/client.ts` — in-memory **mock** client (fixtures + synthetic delays).
- `src/api/realClient.ts` — **real** `fetch` client against the backend.
- `src/api/index.ts` — the **selector**: exports `apiClient`, picking mock vs
  real from `VITE_USE_MOCKS` (default mocks ON). Components and `queries.ts`
  import from here and never branch on which client is live.
- `src/api/schema.gen.ts` — TS types generated from the backend OpenAPI by
  `openapi-typescript` (regenerate with `npm run gen:api`, backend must be up).
- `src/api/mappers.ts` — wire (snake_case) → UI shape translation.

## API client mode + environment variables

| Var | Default | Meaning |
|---|---|---|
| `VITE_USE_MOCKS` | unset → mocks ON | `"false"` switches to the real client. Anything else keeps mocks (offline). |
| `VITE_API_BASE` | `""` (same-origin) | Base URL for the real backend. Leave empty in dev and use the Vite proxy. |

```bash
# Offline (default) — mock client, no backend needed:
npm run dev

# Real backend (same-origin via the dev proxy → http://localhost:8090):
VITE_USE_MOCKS=false npm run dev
# point the proxy elsewhere:
NB_DEV_API_TARGET=http://host:port VITE_USE_MOCKS=false npm run dev
```

The dev server proxies `/api/*` to the backend (`vite.config.ts → server.proxy`,
target `NB_DEV_API_TARGET`, default `http://localhost:8090`) so same-origin
requests avoid CORS.

### Regenerating API types

```bash
# Backend must be running on :8090 (see repo root for launch command):
npm run gen:api   # openapi-typescript http://localhost:8090/openapi.json -o src/api/schema.gen.ts
```

## Stack

- Vite + React 18 + TypeScript strict
- Tailwind CSS (v3) — design tokens are CSS variables in `src/styles/globals.css`
- Typography (self-hosted via `@fontsource`, imported in `src/main.tsx` — no
  CDN, offline-safe): **Sora** for display / wordmark / UI body, **IBM Plex
  Mono** for the data surfaces (port names, VLAN ids, IPs, config). The mono is
  the instrument typeface — monospace is the aesthetic for a network tool.
- `@react-three/fiber` + `@react-three/drei` for 3D
- TanStack Query for server cache, Zustand for UI state
- React Router v6
- vitest for unit tests, Playwright is wired but not seeded

## Running

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
npm run build        # tsc + vite build
npm run lint
npm run typecheck
npm test
```

If `bun` is installed, all `npm` commands above work with `bun` as a drop-in.

## Demo flow

1. Land on `/login`. Username is one of `admin` or `alice`. Any password works.
2. After login: environment picker. Click Lab or DC to enter.
3. Sidebar lists devices grouped by role. Pick one to see the 3D switch.
4. Click a port (in the 3D scene or the strip below) to open the slide-in panel.
5. Press `?` for the keyboard cheat sheet.
6. Use the role pill in the top-right to switch between admin and requester
   and watch the inline buttons change.
7. Click `+` in the sidebar to walk the 7-step onboarding wizard.

## Routes

```
/login                                   Login (mock auth)
/                                        Environment picker (Lab + DC tiles)
/onboard                                 Onboarding wizard (7 steps)
/requests                                My requests (requester) / All requests (admin)
/queue                                   Admin queue (admin only)
/env/:env                                Environment topology (3D)
/env/:env/devices/:deviceId              Device detail (3D switch + port strip)
/env/:env/search?q=...                   Global search results
```

## Project layout

```
src/
├── api/
│   ├── client.ts            Mock REST client. Swap with fetch later.
│   └── queries.ts           React Query keys + hooks.
├── components/
│   ├── three/               R3F 3D switch + topology renderers.
│   ├── layout/              TopBar, Sidebar, NocRibbon.
│   ├── onboarding/          7-step wizard.
│   ├── requests/            Request rows for queue + list.
│   ├── ui/                  Button, Modal, Input, StatusDot, VlanChip, etc.
│   ├── PortPanel.tsx        Slide-in port detail panel.
│   ├── PortStrip.tsx        Horizontal port card strip.
│   ├── PortCard.tsx
│   ├── RequestModal.tsx
│   ├── DeviceConfigView.tsx
│   ├── HelpOverlay.tsx
│   └── Diff.tsx             Field diff + per-platform config diff.
├── hooks/
│   └── useHotkeys.ts        Single-key + sequence shortcut hooks.
├── lib/
│   ├── cn.ts                clsx + tailwind-merge.
│   ├── format.ts            Time/IP/initials helpers.
│   ├── palette.ts           NOC Cyan / Blueprint Amber / Phosphor.
│   ├── vlan.ts              Deterministic VLAN colors (oklch + RGB).
│   └── config.ts            Per-platform config rendering.
├── mocks/
│   ├── fixtures.ts          Device, port, request, audit fixtures.
│   └── registry.ts          Platform driver capabilities.
├── pages/                   One per route. Composition only, no logic.
├── store/
│   ├── auth.ts              Persisted user + role.
│   ├── theme.ts             Persisted dark/light + palette.
│   ├── ui.ts                Selection, modals, sidebar.
│   └── toast.ts             Imperative toast queue.
├── styles/
│   └── globals.css          Design tokens + Tailwind layers.
├── test/
│   └── setup.ts             jest-dom for vitest.
├── types/
│   └── index.ts             Canonical contract (mirror of data.jsx + backend D8).
├── App.tsx                  Routes, hotkeys, global dialogs.
└── main.tsx                 Entry: React Query, palette bootstrap.
```

## Where types live

All API-shaped types are in [`src/types/index.ts`](src/types/index.ts). Do not
inline domain types in components. The mock client and the future real
client both produce values of these shapes.

## Mock data

Translated from `supporting material/data.jsx` into TypeScript in
[`src/mocks/fixtures.ts`](src/mocks/fixtures.ts). Seed is fixed (mulberry32
with `seed=7`) so reloads produce the same data.

Coverage:

- 10 devices: 4 Cisco 24-port leaves, 1 Cisco spine, 1 Arista
  32×100G, 2 Pica8 (48×10G + 32×100G), 2 FreeBSD routers, 1 VPN node.
  (Platform set matches the backend `/api/platforms`: arista, cisco, pica8,
  freebsd, plus a `mock` testing driver.)
- ~280 ports with mixed `up` / `down` / `disabled` state.
- 5 change requests across all statuses.
- 60-entry audit trail.
- 2 users (`admin`, `alice`).

The platform registry is in
[`src/mocks/registry.ts`](src/mocks/registry.ts) and matches the
`DriverCapabilities` shape from `principal-engineering.md` D5.

## Auth flow

- `LoginPage` → `apiClient.login()` → `POST /api/auth/login` → persists
  `{ access_token, username, role }` to `useAuthStore` (localStorage).
- On every protected mount, `useValidateSession` calls `GET /api/users/me`; a
  401 clears the session and the route guard bounces to `/login`.
- The real client attaches `Authorization: Bearer <token>` from the store on
  every request and, on any 401, clears the session + redirects to `/login`.
- Sign out → best-effort `POST /api/auth/logout` + local clear + `/login`.

Under mocks all of the above resolves locally so E2E never needs a server.

## Keyboard shortcuts

| Key   | Action                                         |
| ----- | ---------------------------------------------- |
| `/`   | Focus search                                   |
| `?`   | Help                                           |
| `g h` | Home (env picker)                              |
| `g l` | Switch to Lab                                  |
| `g d` | Switch to DC                                   |
| `g r` | My requests                                    |
| `g q` | Admin queue (admin only)                       |
| `j`   | Next port on selected device                   |
| `k`   | Previous port                                  |
| `r`   | Open request-change modal for selected port    |
| `Esc` | Close panel / modal / clear selection          |

## Notes / deviations

- React Router v6 over TanStack Router. Reason: ecosystem maturity, smaller
  cognitive load for the upcoming backend hand-off, no need for the
  TanStack Router type-safety story given how few routes exist.
- The 3D scene uses instanced meshes only above 60 ports (the Pica8 48-port
  + the Arista/Pica8 100G keep the per-port mesh path so the LED pulse stays
  per-port). For the 280-port composite — when the user is zoomed out into
  topology view — the 3D switch is not rendered.
- `OrbitControls` is pulled from `@react-three/drei`, configured to lock pan
  on the device-detail view (orbit + zoom only) and allow pan in topology.
- The login is purely visual; the mock client returns whichever username
  matches a known user. A real backend swap would hit `/api/auth/login` and
  store the JWT in `useAuthStore`.
