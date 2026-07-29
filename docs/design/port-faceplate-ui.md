# Design — Auto-generated device faceplate & pinned port references

Status: proposed
Scope: `frontend/` only unless a step is explicitly marked **backend**.

## The one rule this design exists to enforce

> **A change request pins the port it was filed against. If the live device no
> longer matches that pin, that is DRIFT TO FLAG — never a silent re-resolve and
> never a silent drop.**

Everything below follows from that sentence. Where the current UI violates it,
the violation is named with a `file:line` anchor.

## Reference — Patchdocs, and where we deliberately diverge

Sources: `docs.patchdocs.io/features/device-library`,
`/core-concepts/resource-types`, `/features/rack-editor`, `patchdocs.io/features`,
and the `06-Device-Library.webm` product demo — read in a real browser session
(these URLs 403 automated fetchers, so plain HTTP clients see nothing).

### Their faceplate model, concretely

This is the part worth copying, because it is a good model and it settles the
"do we need SVG artwork" question:

- The device face is **a grid — two port rows per rack unit** — and every
  element occupies whole grid cells. Devices are 1–8 RU.
- Ports live in **port groups**: rectangular blocks sharing a connector type, a
  label prefix, and one numbering sequence. Max 99 ports per group.
- Group settings are exactly four things: **Prefix** (≤4 chars), **Counting
  Direction**, **Connector Type** (RJ45/copper, or fiber LC/SC/E2000/ST/MPO),
  and fiber mode / connector gender.
- **Port numbers are computed, never typed.** *Top-to-bottom* numbers down each
  column then moves right — which yields the classic switch faceplate, odd on
  top (1,3,5…), even on the bottom (2,4,6…). *Left-to-right* numbers across each
  row. Groups sharing a prefix continue one sequence, ordered left to right,
  with the Back side continuing after the Front.
- Extra elements are only **text fields** and **icons** (1×1 to 2×2 cells).
- Front / Back faces for rear-panel ports.

So a faceplate is rectangles on a grid plus a numbering rule. The photoreal
switch renders on the marketing site are **not** how the app draws devices.

**Consequence for us: no SVG assets and no drawing library.** React renders SVG
natively; the whole faceplate is a `<rect>` grid driven by (group, rows, cols,
prefix, direction). What Patchdocs asks a human to assemble by drag-and-drop,
Northbound can derive from discovered port names — `xe-1/1/5` already encodes
group and index, and the two-rows-per-RU + odd-top/even-bottom convention is
the same physical reality both products are drawing.

### The cautionary finding — why our drift rule is right

Patchdocs' template is the source of truth, and reality loses when they
disagree. From their own docs:

> "Editing a custom device template that is already deployed triggers a
> destructive rebuild — every connection on every deployed instance is
> permanently deleted, along with VLAN and SFP assignments."

and:

> "If the new template is taller than the original, any deployed instance that
> no longer fits in its rack is permanently deleted and not rebuilt."

They mitigate with a typed-name confirmation and a downloadable PDF impact
report — i.e. the damage is accepted as unavoidable and merely documented.

That is the exact failure mode this design forbids. **A template must never be
able to destroy recorded reality.** In Northbound the device is the source of
truth, the faceplate is a rendering of discovered ports, and a template (if we
ever add one) is a presentation override. When template and live inventory
disagree, we flag drift — we never rebuild, never delete connections, never
silently re-resolve. This is the same rule stated at the top of this document,
and Patchdocs is the worked example of what violating it costs.

The rest of the product description below comes from the same sources.

What Patchdocs does (from its features page):

- a "digital twin ... from the building down to the port"
- **custom device templates** — "tailored to your equipment, your naming
  conventions, and your workflows"
- port-level documentation: "every port, every patch, every connection"
- locations → racks → devices → ports → connections
- **visual rack rendering** — "showing you exactly what's installed, where, and
  how everything connects"
- floor plans, photos, notes, full change history
- **reports & export** — "professional reports in seconds", structured data and
  visuals "to share with customers, auditors, or internal teams"
- 2FA and access control
- **multi-customer management** — "manage all your customers in one centralized
  system"

That last pair matters for positioning: Patchdocs is an **MSP documentation-of-
record** product. Its output is a report for a customer or an auditor, and its
input is a human declaring what exists. Northbound is a **live-state control
plane** for one estate: its input is the device itself, and its output is a
change pushed to that device. They overlap only on the port-level visual.

### Connections: the one feature we should NOT copy by hand

"Every patch, every connection" is Patchdocs' headline, and in that product it is
**manually recorded** — a human types which port patches to which. Northbound
already has this discovered, for free:

| Piece | Anchor |
|---|---|
| `get_neighbors(port) -> list[Neighbor]` on the Driver ABC | `drivers/base.py:114` |
| Normalization shared across drivers | `_lib/lldp.py` |
| `supports_lldp` capability per platform | `schemas/driver.py:40` |
| Per-port neighbors already on the wire | `port.neighbors` |
| Already rendered as a "Neighbor (LLDP)" section | `PortPanel.tsx:379-382` |

So the faceplate can draw **discovered** adjacency (chassis id, remote port,
system name) instead of asking anyone to record patches. Build the connection
view on LLDP; do not add a manual patch-entry UI.

Caveat, and it is the same rule as everywhere else in this document: LLDP is
observed truth about what is *currently* plugged in. If a recorded expectation
and the live neighbor disagree, that is drift to flag — not a cue to silently
rewrite the record. `models/index.ts:369` already states the existing boundary:
neighbors are display-only and never auto-onboard a device.

### Deliberately out of scope

- **Racks, buildings, floor plans.** A headline Patchdocs feature; ruled out by
  the user — "racks are not needed, but the switch or router". The unit is the
  device faceplate.
- **Multi-customer / MSP tenancy.** Northbound is single-estate.
- **Manual patch recording.** Superseded by LLDP, per above.

Worth considering later (a real Patchdocs capability with no Northbound
equivalent): **export of the faceplate + port assignments** as a report or
structured data, for audits or handover.

**The key divergence.** Patchdocs is a *manual documentation* tool: it needs
device templates because it has no connection to the live equipment — a human
declares what the device looks like. Northbound *already talks to the device*
and discovers its real port inventory. So we should **generate the faceplate
from discovered ports** and treat a template as an optional override, not the
source of truth. Auto-generation is the whole point of the user's "the ports
and all, auto".

Adopted from Patchdocs: faceplate as the primary surface, port-level detail,
per-port notes/labels, change history.

## Where we are today (verified, not assumed)

| Fact | Anchor |
|---|---|
| A faceplate renderer already exists (R3F) | `components/three/Switch3D.tsx` |
| Layout comes from a fixed enum → rows/cols | `Switch3D.tsx:26-38` (`portLayout`) |
| `portKind` is a **guess from the platform string** | `mappers.ts:69-80` (`portKindFor`) |
| It is assigned once and never refined | `mappers.ts:115` → `Switch3D.tsx:350` |
| 2D port views also exist | `components/PortStrip.tsx`, `PortPanel.tsx`, `PortCard.tsx` |

**The gap.** `portKindFor` maps `arista→qsfp-32`, `pica8→sfp-48`,
`freebsd→rj45-4`, everything else→`rj45-24-2sfp`. Its docstring claims the guess
is "refined once ports are known". A repo-wide search for `portKind` returns 7
references and **none of them refine it** — the comment is false and should be
deleted. Consequence: every pica8 device renders 48 SFP cages regardless of the
port inventory the backend actually discovered.

This is why the faceplate cannot currently be trusted as documentation: it draws
a *platform stereotype*, not *this device*.

## Design

### 1. Derive the faceplate from discovered ports (the "auto" part)

Replace the platform guess with a layout **inferred from the real port list**,
which the backend already returns (`GET /api/devices/{id}/ports`).

New module `lib/faceplate.ts` — single owner of the derivation:

```ts
export interface Faceplate {
  rows: FaceplateRow[];        // ordered top→bottom
  source: 'discovered' | 'platform-fallback';
  uplinks: PortSlot[];         // trailing SFP/QSFP cages, rendered as a group
}
```

Inference inputs, in priority order:

1. **Port name structure** — `xe-1/1/5` → chassis/slot/port; group by the prefix,
   order by the trailing index. This is the strongest signal and needs no
   vendor table.
2. **Media type / speed** — `speed_mbps` and name prefix (`xe`/`ge`/`et`)
   distinguish RJ45 from SFP from QSFP cages.
3. **Count** → rows: ≤6 → 1 row; ≤26 → 2 rows; ≤52 → 4 rows. Standard 1U
   staggering (odd numbers on top).
4. **Fallback** — if ports have not loaded yet, keep the existing
   `portKindFor` stereotype but tag `source: 'platform-fallback'` and render it
   visibly de-emphasised. **The UI must never present a guess as fact.**

Optional later layer: a **device template** (Patchdocs' model) that overrides
the inferred layout for equipment whose physical arrangement can't be derived
from names alone — e.g. odd breakout cages or non-contiguous numbering. A
template is an *override on top of* discovered truth, never a replacement for
it: if the template and the live inventory disagree, that disagreement is drift
to surface, by the same rule as a pinned port reference.

`Switch3D` then consumes `Faceplate` instead of `PortKind`. `PortKind` stays
only as the fallback stereotype.

> Routers and switches use the same renderer — a router is just a faceplate with
> fewer, differently-named ports. No separate component. **No rack view.**

### 2. Pinned references and drift (the rule)

A port reference is `(device_id, port_name)` captured at file time, alongside
the backend's existing `device_state_fingerprint`
(`services/requests.py:246-248`). The UI resolves that pin against live ports
and renders one of exactly three outcomes:

| Outcome | Condition | Render |
|---|---|---|
| **Resolved** | pin matches a live port | normal diff / VLAN chips |
| **Drift** | `port_name` set, no live match | `drift` badge + explicit "not re-resolved" note |
| **Not applicable** | device-level kind, `port_name === ''` | the change target (`VLAN 1234`) |

Already implemented in `lib/changeSummary.ts`
(`hasUnresolvedPortReference`, `isDeviceLevel`) and wired into
`components/requests/RequestRow.tsx`.

**Anti-requirement — do not build these:**

- ❌ fuzzy-matching a pin to a "nearby" port (index±1, similar name)
- ❌ auto-rewriting `port_name` when a device is re-discovered
- ❌ hiding a request whose pin fails to resolve

The third was the actual production bug: `RequestRow.tsx:84` read
`if (!device || !port) return null`, so every device-level request and every
request against an unreachable device silently vanished — while the queue badge
(`TopBar.tsx:57`) still counted them. Users saw "3 in Queue" above an empty
list. **A pin that fails to resolve is information, not a reason to render
nothing.**

### 3. Faceplate as the documentation surface

Per-port overlay state, all already available:

- VLAN colour (untagged) — reuse `lib/vlan.ts` `vlanRGB`
- tagged-VLAN count badge
- link/admin state
- `host_model` / `bmc_ip` labels — the patch-documentation payload
- **pending-change halo** — ports with an open request, so the faceplate shows
  what is *about to* change, not just current state

Selecting a port drives the existing `PortPanel`. The faceplate replaces the
port *picker*, not the port *editor*.

## Staging

| # | Step | Risk |
|---|---|---|
| 1 | `lib/faceplate.ts` + unit tests over real port inventories | none (pure) |
| 2 | Delete the false "refined once ports are known" comment | none |
| 3 | `Switch3D` consumes `Faceplate`; keep stereotype as tagged fallback | low |
| 4 | Overlays (VLAN, tagged count, pending-change halo) | low |
| 5 | Faceplate as picker on `DeviceDetailPage` | medium — real estate |
| 6 | **backend** — expose `_kind` in the OpenAPI contract (see below) | medium |

Steps 1-2 are independent and can land immediately.

## Known contract debt (backend)

`services/requests.py:305,351,395,444` file requests as
`{"_kind": <kind>, **change.model_dump()}` into a field the OpenAPI schema
declares as `PortChange` (`schema.gen.ts:1801`). The discriminator therefore
exists at runtime but is **invisible to generated TypeScript**, which is why
`mapRequest` only ever handled the port shape.

`lib/changeSummary.ts` narrows this defensively at the boundary. The real fix is
a discriminated union in the response model so `schema.gen.ts` carries the
variants and the frontend narrowing becomes type-checked rather than hand-rolled.
Until then the hand-rolled narrowing is load-bearing — do not delete it.
