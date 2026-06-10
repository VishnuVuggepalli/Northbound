/**
 * Wire → UI shape mappers.
 *
 * The backend (FastAPI/Pydantic) speaks snake_case and uses slightly different
 * field names than the UI's hand-written domain types (`environment` vs `env`,
 * timestamps as ISO strings vs epoch ms, no `model`/`portKind` on devices —
 * those are presentation concerns). These functions translate the generated
 * `schema.gen.ts` shapes into the canonical `@/models`. Keeping the translation
 * here means components and the mock client never see the wire shape.
 */

import type { components } from './schema.gen';
import type {
  AuditEntry,
  ChangeRequest,
  Device,
  Platform,
  PlatformId,
  PlatformRegistryEntry,
  Port,
  PortKind,
} from '@/models';

type DeviceOut = components['schemas']['DeviceOut'];
type PortStateOut = components['schemas']['PortStateOut'];
type RequestOut = components['schemas']['RequestOut'];
type AuditEntryOut = components['schemas']['AuditEntryOut'];
type PlatformInfo = components['schemas']['PlatformInfo'];
type DriverCapabilities = components['schemas']['DriverCapabilities'];

/** ISO-8601 (or epoch-ms number) → epoch ms, with a null passthrough. */
export function toEpochMs(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number') return value;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

const KNOWN_PLATFORMS: readonly Platform[] = [
  'arista',
  'cisco',
  'pica8',
  'mikrotik',
  'mikrotik_swos',
  'freebsd',
  'mock',
];

/** Coerce the backend's free-form `platform` string into the UI union. */
export function toPlatform(raw: string): Platform {
  return (KNOWN_PLATFORMS as readonly string[]).includes(raw) ? (raw as Platform) : 'mock';
}

/** Default management port per platform — used when the wire omits it. */
function defaultPortFor(platformId: string): number {
  switch (platformId) {
    case 'pica8':
      return 830;
    case 'freebsd':
      return 22;
    default:
      return 443;
  }
}

/** Physical port layout guess from platform; refined once ports are known. */
function portKindFor(platform: Platform): PortKind {
  switch (platform) {
    case 'arista':
      return 'qsfp-32';
    case 'pica8':
      return 'sfp-48';
    case 'freebsd':
      return 'rj45-4';
    default:
      return 'rj45-24-2sfp';
  }
}

export function mapPlatform(info: PlatformInfo): PlatformRegistryEntry {
  const platform = toPlatform(info.platform_id);
  const caps: DriverCapabilities = info.capabilities;
  return {
    platform_id: info.platform_id as PlatformId,
    platform,
    display_name: info.display_name,
    description: '',
    defaultPort: defaultPortFor(info.platform_id),
    capabilities: {
      writable: caps.writable,
      supports_commit_confirm: caps.supports_commit_confirm,
      native_api_available: caps.native_api_available,
      supports_snmp_read: caps.supports_snmp_read,
      supports_lldp: caps.supports_lldp,
      max_concurrency: caps.max_concurrency,
      auth_methods: [...caps.auth_methods],
    },
    web_ui_url_template: caps.web_ui_url_template ?? null,
  };
}

export function mapDevice(d: DeviceOut, portCount = 0): Device {
  const platform = toPlatform(d.platform);
  return {
    id: d.id,
    name: d.name,
    env: d.environment,
    platform,
    role: d.role,
    mgmt_ip: d.mgmt_ip,
    model: d.platform,
    portCount,
    portKind: portKindFor(platform),
    reachable: d.reachable ?? null,
    writable: d.writable,
    writes_enabled: d.writes_enabled,
    ...(d.ssh_user ? { ssh_user: d.ssh_user } : {}),
  };
}

export function mapPort(p: PortStateOut, deviceId: string, index: number): Port {
  const linkUp = p.link_up;
  const adminUp = p.admin_up;
  const state: Port['state'] = !adminUp ? 'disabled' : linkUp ? 'up' : 'down';
  const services = (p.services ?? {}) as Record<string, boolean>;
  return {
    device_id: deviceId,
    name: p.name,
    index,
    state,
    admin_up: adminUp,
    link_up: linkUp,
    speed_mbps: p.speed_mbps ?? null,
    duplex: (p.duplex as Port['duplex']) ?? null,
    mac: p.mac ?? null,
    mtu: p.mtu ?? 1500,
    untagged_vlan: p.untagged_vlan ?? 0,
    tagged_vlans: [...(p.tagged_vlans ?? [])],
    description: p.description ?? '',
    host_model: p.host_model ?? '',
    bmc_ip: p.bmc_ip ?? '',
    notes: p.notes ?? '',
    // Pass through whatever per-port services the backend reports. Real drivers
    // (pica8/NETCONF) don't model per-port protocol flags -> {} -> the panel's
    // Services section hides itself. No synthesized always-false chips.
    services,
    traffic: 0,
    last_change: toEpochMs(p.last_human_edit_at) ?? Date.now(),
  };
}

/* Runtime narrowing for untrusted wire values (`requested_changes` is a free
 * JSON object on the wire) — a malformed backend value becomes `undefined`
 * instead of a lying compile-time cast. */
const asNumber = (v: unknown): number | undefined => (typeof v === 'number' ? v : undefined);
const asString = (v: unknown): string | undefined => (typeof v === 'string' ? v : undefined);
function asNumberArray(v: unknown): number[] | undefined {
  if (!Array.isArray(v)) return undefined;
  const nums = v.filter((x): x is number => typeof x === 'number');
  return nums.length === v.length ? nums : undefined;
}

export function mapRequest(r: RequestOut): ChangeRequest {
  const changes = (r.requested_changes ?? {}) as Record<string, unknown>;
  return {
    id: r.id,
    device_id: r.device_id,
    port_name: r.port_name,
    requested_by: r.requested_by,
    requested_by_username: r.requested_by_username ?? null,
    requested_changes: {
      untagged_vlan: asNumber(changes.untagged_vlan),
      tagged_vlans: asNumberArray(changes.tagged_vlans),
      host_model: asString(changes.host_model),
      bmc_ip: asString(changes.bmc_ip),
      notes: asString(changes.notes),
    },
    reason: r.reason,
    status: r.status,
    reviewer_id: r.reviewer_id ?? null,
    reviewer_comment: r.reviewer_comment ?? '',
    created_at: toEpochMs(r.created_at) ?? Date.now(),
    reviewed_at: toEpochMs(r.reviewed_at),
    applied_at: toEpochMs(r.applied_at),
  };
}

export function mapAudit(a: AuditEntryOut): AuditEntry {
  const created = toEpochMs(a.created_at) ?? Date.now();
  const agoMinutes = Math.max(0, Math.floor((Date.now() - created) / 60_000));
  const beforeAfter =
    a.before || a.after ? `${JSON.stringify(a.before ?? {})} → ${JSON.stringify(a.after ?? {})}` : a.result;
  return {
    id: a.id,
    device_id: a.target_device_id ?? '',
    port_name: a.target_port ?? '',
    user: a.user_id ?? 'system',
    action: a.action,
    ago_minutes: agoMinutes,
    summary: beforeAfter,
  };
}
