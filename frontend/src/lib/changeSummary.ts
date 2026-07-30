/**
 * Human-readable summaries for change requests of any kind.
 *
 * Why this exists: `requested_changes` is a free-form JSON object on the wire
 * whose shape depends on the backend's `_kind` discriminator (see
 * `services/requests.py`). The UI previously understood only the per-port
 * shape, so vlan/l3/vrf/ospf requests rendered as blank rows. This module is
 * the single place that turns `(kind, params)` into display text.
 *
 * Values are read defensively: every field is untrusted wire data, so a missing
 * or wrong-typed value degrades to a placeholder rather than throwing or
 * rendering `undefined`.
 */

import type { ChangeKind, ChangeRequest } from '@/models';

/** One label/value pair rendered as a chip or KV row. */
export interface ChangeDetail {
  label: string;
  value: string;
}

export interface ChangeSummary {
  /** Short target line, e.g. `VLAN 1234` or `SVI vlan3997`. */
  target: string;
  /** The verb, e.g. `create` / `delete` / `set`. Empty when the payload omits it. */
  action: string;
  /** Ordered detail chips — only fields actually present in the payload. */
  details: ChangeDetail[];
}

const KIND_LABEL: Record<ChangeKind, string> = {
  port: 'Port',
  vlan: 'VLAN',
  l3: 'L3',
  vrf: 'VRF',
  ospf: 'OSPF',
};

/** Display label for a change kind (`'vlan'` → `'VLAN'`). */
export function changeKindLabel(kind: ChangeKind): string {
  return KIND_LABEL[kind] ?? kind;
}

/**
 * Present-and-meaningful check. The backend emits explicit `null`s for unset
 * optional fields (`model_dump()` with `exclude_none=False`), so `null`,
 * `undefined` and `''` all mean "not part of this change".
 */
function present(v: unknown): boolean {
  return v !== null && v !== undefined && v !== '';
}

/** Render an untrusted wire value as display text. */
function text(v: unknown): string {
  if (typeof v === 'string') return v;
  if (typeof v === 'number') return String(v);
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (Array.isArray(v)) return v.map(text).join(', ');
  return '';
}

/** Push a detail chip only when the underlying value is actually set. */
function push(into: ChangeDetail[], label: string, value: unknown): void {
  if (present(value)) into.push({ label, value: text(value) });
}

function summarizeVlan(p: Readonly<Record<string, unknown>>): ChangeSummary {
  const details: ChangeDetail[] = [];
  push(details, 'name', p.name);
  push(details, 'description', p.description);
  return {
    target: present(p.vlan_id) ? `VLAN ${text(p.vlan_id)}` : 'VLAN',
    action: text(p.action),
    details,
  };
}

function summarizeL3(p: Readonly<Record<string, unknown>>): ChangeSummary {
  // NOTE: the l3 payload has its own `kind` field ("svi" | "loopback"), which is
  // NOT the `_kind` discriminator. Keep them distinct — conflating them was the
  // original source of confusion.
  const ifaceKind = text(p.kind).toUpperCase();
  const name = present(p.name)
    ? text(p.name)
    : present(p.vlan_id)
      ? `vlan${text(p.vlan_id)}`
      : '';
  const details: ChangeDetail[] = [];
  push(details, 'ipv4', p.ipv4);
  push(details, 'vrf', p.vrf);
  push(details, 'mtu', p.mtu);
  push(details, 'dhcp', p.dhcp);
  push(details, 'enabled', p.enabled);
  return {
    target: [ifaceKind, name].filter(Boolean).join(' ') || 'L3 interface',
    action: text(p.action),
    details,
  };
}

function summarizeVrf(p: Readonly<Record<string, unknown>>): ChangeSummary {
  const details: ChangeDetail[] = [];
  push(details, 'description', p.description);
  return {
    target: present(p.name) ? `VRF ${text(p.name)}` : 'VRF',
    action: text(p.action),
    details,
  };
}

function summarizeOspf(p: Readonly<Record<string, unknown>>): ChangeSummary {
  const details: ChangeDetail[] = [];
  push(details, 'area', p.area);
  push(details, 'router-id', p.router_id);
  push(details, 'cost', p.cost);
  push(details, 'hello', p.hello_interval);
  push(details, 'dead', p.dead_interval);
  push(details, 'passive', p.passive);
  const target = present(p.interface)
    ? `OSPF ${text(p.interface)}`
    : present(p.target)
      ? `OSPF ${text(p.target)}`
      : 'OSPF';
  return { target, action: text(p.action), details };
}

function summarizePort(p: Readonly<Record<string, unknown>>): ChangeSummary {
  const details: ChangeDetail[] = [];
  push(details, 'untagged', p.untagged_vlan);
  if (Array.isArray(p.tagged_vlans) && p.tagged_vlans.length > 0) {
    push(details, 'tagged', p.tagged_vlans);
  }
  push(details, 'mode', p.port_mode);
  push(details, 'mtu', p.mtu);
  push(details, 'enabled', p.enabled);
  push(details, 'host', p.host_model);
  push(details, 'bmc', p.bmc_ip);
  push(details, 'description', p.description);
  return { target: 'Port', action: '', details };
}

/**
 * Summarize a change request for display.
 *
 * Dispatches on the request's `kind`, mirroring change_apply.py's own dispatch
 * so the UI describes exactly what the apply flow will act on.
 */
export function summarizeChange(request: ChangeRequest): ChangeSummary {
  const p = request.change_params;
  switch (request.kind) {
    case 'vlan':
      return summarizeVlan(p);
    case 'l3':
      return summarizeL3(p);
    case 'vrf':
      return summarizeVrf(p);
    case 'ospf':
      return summarizeOspf(p);
    case 'port':
      return summarizePort(p);
  }
}

/**
 * Is this a device-level change (no switchport target)?
 *
 * Device-level kinds are filed with an empty `port_name`, so callers must not
 * try to resolve a port for them — the absence is expected, NOT drift.
 */
export function isDeviceLevel(request: ChangeRequest): boolean {
  return request.kind !== 'port';
}

/**
 * Does this request pin a switchport that no longer resolves on the device?
 *
 * The request pins the port it was filed against. If that port is missing from
 * the live device we surface it as drift to flag — we never silently re-resolve
 * to a different port or quietly render nothing.
 */
export function hasUnresolvedPortReference(
  request: ChangeRequest,
  port: { name: string } | undefined,
): boolean {
  return !isDeviceLevel(request) && request.port_name !== '' && port === undefined;
}
