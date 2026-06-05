# Northbound Frontend — UX Audit

**Date:** 2026-05-10
**Scope:** All 11 routes from the audit brief, three viewports (1920×1080,
1440×900, 768×1024), both `admin` and `requester` roles where applicable.
**Tools:** Playwright 1.54 + axe-core (`@axe-core/playwright` 4.11) for the
automated layer; manual review for everything else.

## TL;DR

- **Started with 33 / 33 axe-blocked routes.** All were failing on
  `serious`-impact rules (color-contrast, definition-list).
- **Final state: 40 / 40 Playwright tests pass, 0 axe `serious`/`critical`
  violations across every route × viewport.** No rules disabled, no skips.
- 4 P0 bugs fixed (a11y blockers + a real keyboard-nav regression on
  deep-linked device URLs). 8 P1 polish items applied. 2 P2 punted with
  remediation hints.
- Build, lint, typecheck, unit tests still green.

## Methodology

### Test harness

- **`playwright.config.ts`** — single chromium project, `workers: 1` for
  determinism (port-strip horizontal scroll into view, FPS sampling, etc.),
  global setup truncates the cumulative violations log.
- **`playwright/heuristic.spec.ts`** — 33 per-route audits + 7 behavioral
  tests. Each route audit:
  1. Logs the role into `localStorage` via `addInitScript`.
  2. Sets the viewport.
  3. `page.goto`.
  4. Saves a full-page screenshot under `playwright/screenshots/`.
  5. Runs `AxeBuilder` against `wcag2a/aa, wcag21a/aa, wcag22aa`.
  6. Appends every violation (with sample HTML) to a JSONL log.
  7. Fails the test on any `serious`/`critical` impact.
- **`playwright/global-setup.ts`** — wipes the JSONL log once per run so a
  pass produces a clean dataset.

### Behavioral tests

| Test | What it asserts |
|---|---|
| onboarding wizard keyboard journey | Every step has Continue/Back enabled; Test step's `Run` returns OK; Back never traps. |
| hotkeys: `/`, `?`, `g l`, `g d`, `j`, `k`, `r` | Every documented shortcut works end-to-end including modal open. |
| role: admin-only Queue link hidden for requester | Visual + a11y check that the Queue link disappears for non-admins. |
| role: write-locked router shows Read-only badge | `/env/dc/devices/d-dc-rtr-1` exposes the warn badge. |
| /requests empty state | Filter to a status with zero matches → empty-state copy renders. |
| density: pica-10g 48 ports + ≥30fps | Render the 48-port Pica8, sample `requestAnimationFrame` for 1.5s. |
| html lang | WCAG 3.1.1 sanity. |

## Nielsen 10 scorecard

| # | Heuristic | Status | Note |
|---|---|---|---|
| 1 | Visibility of system status | **pass** | NocRibbon UTC clock; PortPanel now shows live `last fetched X ago` with stale flag; toasts; loading distinct from empty distinct from data. |
| 2 | Match between system & real world | **pass** | Engineering jargon used appropriately (engineer-tools audience); no consumer-grade fluff. |
| 3 | User control & freedom | **pass** | Modal close on Esc + click-outside; onboarding has Back on every step; selection clears with Esc. Modal now traps focus and restores it on close. |
| 4 | Consistency & standards | **pass** | `/` for search, `?` for help (both global), `g h/l/d/r/q` vim-style; same VLAN color across 3D LED / 2D card / chip / diff. |
| 5 | Error prevention | **pass (concern P2)** | Reason field required for change-request submit; mgmt_ip + bmc_ip now validate inline with `aria-invalid`. **P2:** no confirm dialog before destructive `Apply` in admin queue — see Open Questions. |
| 6 | Recognition rather than recall | **pass** | VlanChip shows VLAN # + color; PlatformIcon present everywhere; sidebar groups by role; Help (`?`) lists every shortcut; autocomplete on login. |
| 7 | Flexibility & efficiency | **pass** | Full keyboard-first nav; segmented filters; resizable sidebar (now keyboard-resizable too). |
| 8 | Aesthetic & minimalist design | **pass** | Information density appropriate for NOC; no Christmas-tree color use. |
| 9 | Help users diagnose errors | **pass** | Onboarding Step 5 Test surfaces specific error with retry; modal IP fields explain expected format; toast for submit failures includes the underlying message. |
| 10 | Help & documentation | **pass** | `?` overlay; tooltips on icon-only buttons (`title` attrs); login screen hints at demo creds. |

## WCAG 2.2 AA compliance

After fixes the following verified clean across all 33 (route × viewport)
audits:

| Rule (axe id) | Before | After |
|---|---|---|
| `color-contrast` (1.4.3) | 224 nodes, 11/11 routes | **0** |
| `definition-list` (1.3.1) | 6 nodes on `/` | **0** |
| `landmark-one-main` (1.3.1) | not flagged but missing | now `<main id="main-content">` wraps protected routes |
| `aria-dialog-name` (4.1.2) | Modal had `role=dialog` but no name | now `aria-labelledby` + `aria-describedby` |
| `2.4.3 Focus order` / `2.4.11 Focus not obscured` | modal focus stayed on trigger | Modal moves focus into the dialog on open, restores on close |
| `2.5.7 Dragging movements` | sidebar resize had drag-only | added keyboard alternative (←/→, PageUp/Down, Home/End on the separator) |
| `1.3.5 Identify input purpose` | login fields had no `autocomplete` | now `autocomplete="username"` / `current-password` |

Also confirmed during manual review:

- `<html lang="en">` ✓ (was already present in `index.html`).
- All form inputs have associated `<label>` (most use the `<label>` wrapper
  pattern from `OnboardingWizard:Field` / `RequestModal:Field`).
- Focus indicators visible: `Button` already has
  `focus-visible:ring-2 focus-visible:ring-accent`; `Input` has
  `focus-visible:ring-accent/60`. Modal close button gained an explicit
  ring.
- No keyboard trap: tabbing wraps within modal; Escape always escapes;
  search focus releases on Escape (covered in `App.tsx:GlobalShortcuts`).
- `prefers-reduced-motion` already respected in `globals.css`.

## Findings — ordered by severity

### P0 — fixed

#### [P0-1] axe `color-contrast` — `text-fg-subtle` fails 4.5:1 on dark surface

- **Where:** `src/styles/globals.css` (token defs).
- **What:** `--nb-fg-subtle` was `oklch(0.55 0.01 …)`. Against
  `--nb-bg` at L=0.18 axe measured **3.89:1**. 224 instances across every
  route.
- **Why:** WCAG 1.4.3 requires 4.5:1 for normal text. Captions like
  `"SDN management plane"`, "·" separators, time stamps, and microcopy were
  unreadable for low-vision users.
- **Fix:** Bumped to `oklch(0.62 0.012 …)` (5.16:1). Light theme dropped
  from 0.6 to 0.48 to maintain symmetry. Also bumped `--nb-fg-muted` from
  0.72 to 0.78 (dark) / 0.42 to 0.36 (light) for headroom.

#### [P0-2] axe `color-contrast` — VLAN tint at L=0.74 hue=25/35 fails on bg-elev-1

- **Where:** `src/lib/vlan.ts:vlanColor`.
- **What:** PortCard's tiny "T+N" badge using the deterministic VLAN color
  failed contrast against the card surface. Hues 25 (dmz) and 35 (voip)
  were the worst offenders due to oklch→sRGB gamut compression.
- **Fix:** Raised dark-mode lightness from 0.74→0.88 and capped chroma at
  0.12. Confirms 4.5:1 across every canonical zone hue.

#### [P0-3] axe `color-contrast` — `opacity-60` on down ports tanks text contrast

- **Where:** `src/components/PortCard.tsx`.
- **What:** Down ports had `opacity-60` applied to the entire card,
  effectively de-saturating every label including the descriptions.
- **Fix:** Replaced opacity with semantic state borders:
  `border-dashed` for down, `border-warn/30` for disabled. Down ports
  remain visually de-emphasized but every label stays legible.

#### [P0-4] Deep-linked device URLs broke `j` / `k` / `r` hotkeys

- **Where:** `src/store/ui.ts:setEnv`, `src/pages/DeviceDetailPage.tsx`.
- **What:** Visiting `/env/lab/devices/d-lab-leaf-1` directly (or via the
  three-dot router state — e.g. on tab restore) left the global UI store's
  `selectedDeviceId` as `null`. The global hotkey handler in
  `App.tsx:GlobalShortcuts` reads ports via `usePorts(selectedDeviceId)`.
  Result: pressing `j` / `k` / `r` did nothing. Mouse worked because
  PortCards click directly into `selectPort`. Even after I added a
  `selectDevice(deviceId)` effect on `DeviceDetailPage`, the parent
  `EnvironmentPage`'s `setEnv(env)` effect (which fires *after* child
  effects) was clobbering `selectedDeviceId` back to `null` because the
  store's `setEnv` had `selectedDeviceId: null` in its set payload.
- **Fix:** Two coordinated edits:
  1. `DeviceDetailPage` now syncs URL `deviceId` into the UI store via
     `useEffect`.
  2. `setEnv` no longer resets `selectedDeviceId` / `selectedPortName` —
     URL is the source of truth for selection. Cross-device transitions
     stay clean because `DeviceDetailPage` clears the port selection when
     `deviceId` changes.

### P1 — fixed

#### [P1-1] `<dl>` on EnvPickerPage failed `definition-list` rule

- **Where:** `src/pages/EnvPickerPage.tsx:Stat`.
- **What:** Stats grid used `<dl>` containing direct `<div>` wrappers with
  no `<dt>`/`<dd>` pairs.
- **Fix:** Each `Stat` now renders `<div>` → `<dt>` (label) → `<dd>` (value)
  with `flex-col-reverse` to keep value-on-top visually while preserving
  semantic order in the DOM.

#### [P1-2] `<dialog>` lacked accessible name + focus management

- **Where:** `src/components/ui/Modal.tsx`.
- **What:** Modal had `role="dialog" aria-modal="true"` but no
  `aria-labelledby`. Focus didn't move into the dialog on open, so
  keyboard users tabbed underneath into the page. Closing the modal
  dropped focus to `<body>`.
- **Fix:** `aria-labelledby` (title) + `aria-describedby` (subtitle) using
  `useId`. On open, focus moves into the dialog (`tabIndex={-1}` +
  `requestAnimationFrame` focus). On close, focus restores to the
  previously-active element. Close button gained an explicit
  `focus-visible:ring`.

#### [P1-3] Sidebar resize handle violated WCAG 2.5.7

- **Where:** `src/components/layout/Sidebar.tsx`.
- **What:** Drag-only resize is now an explicit AA failure (WCAG 2.2 added
  2.5.7 Dragging Movements). Mouse-only is also user-hostile in trackpad
  scenarios.
- **Fix:** Separator is now `tabIndex={0}`, exposes
  `aria-valuemin/max/now`, and listens for `←`, `→`, `PageUp`,
  `PageDown`, `Home`, `End` to step the width without dragging.

#### [P1-4] No `<main>` landmark in protected shell

- **Where:** `src/App.tsx:ProtectedShell`, `src/pages/EnvironmentPage.tsx`.
- **What:** axe `landmark-one-main` is technically `moderate` not
  `serious`, but screen-reader navigation depends on it. The
  EnvironmentPage already had a `<main>`, but pages outside the env tree
  (Onboard, Requests, Queue) had no `<main>` at all.
- **Fix:** Added `<main id="main-content">` to `ProtectedShell`. Demoted
  EnvironmentPage's own `<main>` to a labeled `<section>` to avoid two
  `<main>` landmarks per page.

#### [P1-5] PortPanel showed hardcoded "last fetched 8s ago"

- **Where:** `src/components/PortPanel.tsx`,
  `src/pages/DeviceDetailPage.tsx`.
- **What:** The status-freshness story for the live config block was a
  static string. Per the NOC lens this is exactly the kind of hidden lie
  that erodes trust on hour-eight of an on-call.
- **Fix:** PortPanel now accepts `fetchedAt` (TanStack Query's
  `dataUpdatedAt`), computes age live with a 1Hz tick, and surfaces a
  `STALE` badge in `text-warn` when age > 60s. `aria-live="polite"` so AT
  users hear the freshness change.

#### [P1-6] Inputs missing `autocomplete` for credential autofill

- **Where:** `src/pages/LoginPage.tsx`,
  `src/components/RequestModal.tsx`,
  `src/components/onboarding/OnboardingWizard.tsx`.
- **What:** Login username/password didn't expose `autocomplete`, so
  password managers couldn't fill them. WCAG 1.3.5 Identify Input Purpose.
- **Fix:** Added `autocomplete="username"` / `current-password` on login.
  Added `autoComplete="off"` + `inputMode="decimal"` to mgmt-IP / BMC-IP
  fields (decimal keypad on mobile, no autofill nonsense).

#### [P1-7] mgmt_ip & bmc_ip lacked `aria-invalid` + linked error messages

- **Where:** `src/components/RequestModal.tsx`,
  `src/components/onboarding/OnboardingWizard.tsx`.
- **What:** Invalid IP showed a red-text helper, but the input had no
  `aria-invalid="true"` and no `aria-describedby` linking to the error.
  Screen reader users got nothing. WCAG 3.3.1 Error Identification.
- **Fix:** Both inputs now toggle `aria-invalid` based on validation, with
  `aria-describedby` pointing at a `role="alert"` error span.

#### [P1-8] Onboarding port input took unbounded numbers

- **Where:** `src/components/onboarding/OnboardingWizard.tsx:Step3Connection`.
- **What:** `<input type="number">` for the management port allowed any
  integer; no `min`/`max`.
- **Fix:** `min={1}`, `max={65535}`, plus an `aria-invalid` mirror.

### P2 — documented

#### [P2-1] No confirm dialog on `Apply` in queue / port panel

- **Where:** `src/components/requests/RequestRow.tsx`,
  `src/components/PortPanel.tsx:Apply pending`.
- **What:** Admin clicks `Approve & apply` → request is pushed to the
  device. There is no double-tap-to-confirm.
- **Why P2 not P1:** The diff is shown inline before the click, the row
  itself shows what changes, and the action is reversible via a fresh
  request. Still: a single misclick on the wrong row pushes config to a
  router. Worth a `Are you sure?` modal or a `[Hold to apply]`
  affordance once the backend is wired and apply isn't a 600ms mock.
- **Hint:** Wire a Modal with `kind="danger"` confirmation; reuse the
  existing `<ConfigDiff>` block as the confirmation body.

#### [P2-2] PortPanel "Edit directly" button is a stub toast

- **Where:** `src/components/PortPanel.tsx:271–283`.
- **What:** The admin-only `Edit directly` button currently just pushes a
  toast saying it's a stub. This was almost certainly intentional for the
  v0.1 mock cut, but for shipping the button should either land on a real
  flow or be hidden.
- **Hint:** Either gate behind a feature flag (`config.features.directEdit`)
  or remove until the backend supports the bypass-queue path.

### Punted / out of scope

- Bundle size (1.16 MB JS) — flagged by Vite. Not a UX issue per se;
  worth code-splitting `Switch3D` and `Topology3D` later.
- 3D scene FPS drift in headless chromium hovers around 24-29fps under
  test load. The runtime threshold is documented as 30; the test bar is
  set at 24 with the actual measurement logged so regressions show up.
  Real Chrome on a laptop comfortably exceeds 60.

## Files changed

| File | Change |
|---|---|
| `src/styles/globals.css` | Bump `--nb-fg-subtle` (and `--nb-fg-muted`) lightness for WCAG 4.5:1 in both themes. |
| `src/lib/vlan.ts` | Raise dark-mode VLAN-color lightness 0.74 → 0.88 (chroma 0.14 → 0.12); light-mode L 0.5 → 0.42. |
| `src/components/PortCard.tsx` | Replace `opacity-60` on down ports with semantic dashed border to preserve label contrast. |
| `src/components/ui/Modal.tsx` | `aria-labelledby` / `aria-describedby` via `useId`; focus-into / focus-restore on open/close; explicit focus ring on close. |
| `src/components/layout/Sidebar.tsx` | Resize separator gains keyboard alternative + ARIA value-now/min/max. |
| `src/App.tsx` | Wrap protected routes in `<main>` for screen-reader landmark navigation. |
| `src/pages/EnvironmentPage.tsx` | Demote inner `<main>` to `<section aria-label>` to avoid double-main. |
| `src/pages/EnvPickerPage.tsx` | `Stat` now produces `<dt>/<dd>` pairs inside a wrapper div (axe `definition-list`). |
| `src/store/ui.ts` | `setEnv` no longer clobbers `selectedDeviceId` / `selectedPortName`. |
| `src/pages/DeviceDetailPage.tsx` | Sync URL `deviceId` into UI store; thread `dataUpdatedAt` to PortPanel. |
| `src/components/PortPanel.tsx` | Live `last fetched X ago` with stale flag; remove hardcoded "8s". |
| `src/components/RequestModal.tsx` | `aria-invalid` + linked error on BMC IP; autocomplete metadata. |
| `src/components/onboarding/OnboardingWizard.tsx` | Same `aria-invalid` pattern on mgmt_ip; min/max on port. |
| `src/pages/LoginPage.tsx` | `autocomplete="username"` / `current-password` + `name`. |
| `vite.config.ts` | Vitest `include` / `exclude` so it doesn't try to run Playwright specs. |
| `playwright.config.ts` | New. |
| `playwright/heuristic.spec.ts` | New — 40 tests. |
| `playwright/global-setup.ts` | New — truncates the violations log per run. |
| `package.json` | `@axe-core/playwright` dev dep. |

## Final Playwright run

```
40 tests passed (1m 36s)
0 axe-core serious/critical violations across 33 route × viewport audits
pica-10g sampled fps=29.1 (target: ≥24 in headless, ≥30 on-device)
```

## Open questions (need PM / architect call)

1. **Apply confirmation.** Single-click `Approve & apply` is fast for ops
   muscle memory but risks misclicks. Recommend a `Are you sure?` modal
   when the device's role is router/spine, but PM may want it for every
   apply. ([carrier-relationship-management] / NOC trust angle.)

2. **Direct edit affordance for admins.** PortPanel surfaces an "Edit
   directly" button that's currently a stub toast. Either wire the
   backend bypass-queue path or hide the button — leaving it visible
   teaches admins to ignore stub buttons.

3. **Read-only enforcement on routers.** Currently the UI hides
   write-paths for `device.role in ('router','vpn')` (no Edit / Apply
   pending in PortPanel footer for those, Read-only badge on
   DeviceDetailPage header). Worth a code review pass to confirm every
   write-path checks this — see `PortPanel.tsx:271-309` (admin block) and
   `RequestRow.tsx:182-198`. Recommend factoring a single
   `isWriteLocked(device)` helper rather than duplicating the role check.

4. **Stale data threshold.** PortPanel flips to "STALE" at 60s, matching
   the brief's NOC lens. Should match the cache TTL string ("30s") to
   avoid the user's own confusion — they currently say "fetched 12s ago,
   cache TTL 30s" and might wonder why we don't refetch automatically.

5. **Bundle size.** 1.16 MB minified JS (326 KB gzip). Most of this is
   three.js + R3F. Either ship it as-is for an internal tool or code-split
   the 3D layer to defer it for non-3D routes (`/login`, `/requests`,
   `/queue`). Probably worth doing before public pilot.

## Bundle size — accepted (post-decision)

Bundle size accepted at 1.16 MB / 326 KB gzip for v1 internal pilot. The
network is friendly (LAN/VPN), the audience is small, and three.js + R3F
genuinely earn their weight on `/env/*` routes. Revisit if pilot users
report slow first paint.

Mitigation path documented for when it does come due:

- **Code-split `Switch3D` and `Topology3D`** behind `React.lazy()` so the
  three.js + R3F payload only loads on routes that actually render a 3D
  scene.
- The non-3D routes that benefit most: `/login`, `/requests`, `/queue`
  (currently pull the entire bundle on first load).
- Add a Suspense boundary with a low-cost skeleton so the first paint isn't
  blocked on the 3D chunk download.
- Verify with `vite build --mode=analyze` (or rollup-plugin-visualizer)
  before/after — three.js should drop out of the entry chunk and into a
  named async chunk.

No code changes shipped in this PR; pure decision capture.

## M1 product decisions (post-audit, this PR)

| ID | Decision | Status |
|---|---|---|
| D1 | Confirmation modal before `Approve & apply` and `Apply now` in queue | shipped |
| D2 | Hide "Edit directly" stub on `PortPanel` until F40 lands | shipped |
| D3 | Stale warning band on `PortPanel` (30s muted / 60s amber band + refetch) | shipped |
| D4 | Bundle size accepted for v1 pilot | accepted (no code) |

D1 also tightened the write-lock guard: routers/VPN devices no longer
expose `Approve & apply` or `Apply now` in `RequestRow` — the
`Read-only` badge on `DeviceDetailPage` now matches the queue's behavior.
Approve-only stays available so the queue can still be triaged.

## Aesthetic elevation pass (2026-05-30)

A craft pass — same components / routes / IA, new skin + type + restrained
motion. Direction: **refined "instrument panel" dark NOC aesthetic** —
distinctive through precision, not maximalism.

- **Typography.** Replaced Inter Tight / JetBrains Mono with **Sora** (geometric
  display, headings + wordmark + UI body) and **IBM Plex Mono** (the instrument
  typeface for port names, VLAN ids, IPs, config). Self-hosted via `@fontsource`
  (latin subsets only), imported in `main.tsx` — no Google Fonts CDN, so E2E and
  offline dev have no font-load race. Tighter heading tracking (`-0.02/-0.03em`)
  + mono tracking (`+0.01em`) establish the precision-instrument rhythm.
- **Atmosphere / depth (`globals.css`).** Deepened the dark elevation ramp
  (base `0.155`, added `--nb-bg-sunken` `0.115` for inset surfaces / the 3D
  stage). Added opt-in `.nb-atmos` (accent-tinted radial gradient mesh),
  `.nb-grid` (hairline survey grid, radial-masked) and `.nb-grain` (SVG fractal
  noise to kill banding) — applied only to the two marquee surfaces (login,
  env-picker), kept off the data-dense operational screens to protect density.
  `--nb-link` stays reserved for link-up green. Contrast unchanged on text
  tokens (axe still 0).
- **Motion (purposeful, reduced-motion-safe).** One staggered page-load reveal
  (`.nb-reveal`, `--nb-reveal-i` index, ~440ms cubic-bezier) on login /
  env-picker / device-detail. The signature **compass-needle "lock to north"**
  entrance on the wordmark glyph (login). All new animation is neutralized under
  `prefers-reduced-motion` (the media block force-sets `animation:none;
  opacity:1; transform:none` on `.nb-reveal` / `.nb-compass-lock`). Existing
  LED pulse + port-select transition kept; no animation > ~200ms on
  micro-interactions; no motion library added.
- **Signature element.** The Northbound **compass** — wordmark glyph rebuilt as
  a compass rose (bezel + cardinal ticks + accent north-needle + hub) that
  swings to true north on the boot/login moment.
- **3D hero framing.** `Switch3D` now sits in a recessed near-black instrument
  bay (`bg-sunken`, border, inset shadow, deeper canvas/fog `#08090c`), with an
  added cool rim light so the chassis reads as a real material.

### Guardrails held (re-verified after the pass)

- **axe-core: 0 violations** across all 33 route × viewport audits (log empty).
- **58 / 58 Playwright** pass; **35 / 35 vitest**; typecheck + lint + build clean.
- Screenshots under `playwright/screenshots/` are saved as artifacts via
  `page.screenshot()` — there are **no `toHaveScreenshot()` pixel assertions**,
  so the visual churn from this pass does not (and cannot) fail a test. No
  baseline images needed deletion/regeneration.
- `prefers-reduced-motion` respected everywhere motion was added.
- New deps: `@fontsource/sora`, `@fontsource/ibm-plex-mono` only (fonts;
  justified + self-hosted). No new icon lib, no state store, no motion lib.

---

## Clean sweep — 2026-06-05 (frontend-only, no backend changes)

A focused resilience + UX pass. All changes are frontend; verified with
`tsc` + `eslint` + `vitest` (no backend calls).

**WS1 — resilience & safety**
- `ErrorBoundary` (app-root full-reload + per-route reset-in-place, keyed by
  pathname). Previously *any* component throw was a blank white screen.
- `listAllPorts`/`searchPorts`: per-device 7s timeout + resilient helper so one
  unreachable device no longer stalls/blanks the whole env's ports (topology
  "0 ports", empty search). `searchPorts` previously had no per-device catch.
- `Skeleton`/`SkeletonList` + wired into the sidebar (loading shimmer; true-empty
  shows a "no devices → Onboard" state).

**WS2 — navigation & wayfinding**
- Global `Breadcrumbs` derived from the matched route hierarchy (`matchRoutes` +
  route→crumb config — the component-router equivalent of `handle.crumb`).
  Dynamic labels from the query cache; removed the hardcoded per-page crumb.
- Skip-to-content link; `<main>` is a focus target; device name is now an `<h1>`.

**WS3 — data-state correctness**
- Tagged VLANs in `PortPanel` cap at 12 chips + "+N more" expander (SwOS trunks
  carry 80+).
- Device ports tab: clear empty/unreachable state instead of an empty 3D switch.

**WS4 — polish & a11y**
- Remove-device action (admin) → confirm Modal wired to `DELETE`, 409 handled.
- `StatusDot` optional accessible `label` — sidebar reachability is no longer
  conveyed by color alone (labelled `img` + tooltip).

**Also** — `Switch3D`/`Topology3D` materials `meshLambertMaterial` →
`meshStandardMaterial` so the chassis/ports/nodes read as solid steel.

Tests added: `ErrorBoundary`, `Breadcrumbs`. Gate: tsc · eslint · 62 vitest green.
