/**
 * Northbound — canonical types
 *
 * These mirror `supporting material/data.jsx` and the v1 backend contract
 * described in `principal-engineering.md`. The mock API client and the future
 * real client both produce values of these shapes; UI components consume them
 * unchanged.
 */

/**
 * A site slug — the URL-safe identifier of a runtime-managed site (formerly the
 * fixed `'lab' | 'dc'` enum). Now a free-form string backed by the sites
 * catalog; see {@link Site} and `GET /api/sites`.
 */
export type Environment = string;

/** A site in the catalog (location/environment a device lives in). */
export interface Site {
  id: string;
  slug: string;
  name: string;
  deviceCount: number;
}
/**
 * Broad device-facing platform category. Matches the real backend's
 * `/api/platforms` set: arista, cisco, pica8, freebsd (+ `mock` for testing).
 * MikroTik was dropped when the backend driver set was finalized.
 */
export type Platform = 'arista' | 'cisco' | 'pica8' | 'freebsd' | 'mock';
export type DeviceRole = 'leaf' | 'spine' | 'router' | 'vpn';
export type UserRole = 'admin' | 'requester';
export type PortState = 'up' | 'down' | 'disabled';

/**
 * Port physical layout — drives 3D rendering and 2D card density.
 *
 * - `rj45-24-2sfp`  → 24× RJ45 in 2 rows of 12 + 2× SFP+ on the right
 * - `sfp-5`         → 5× SFP+ inline (legacy compact-spine layout)
 * - `qsfp-32`       → 32× QSFP28 in 2 rows of 16 (Arista / Pica8 100G)
 * - `sfp-48`        → 48× SFP+ in 4 rows of 12 (Pica8 10G)
 * - `rj45-4`        → 4× RJ45 (FreeBSD-style 1U server)
 */
export type PortKind =
  | 'rj45-24-2sfp'
  | 'sfp-5'
  | 'qsfp-32'
  | 'sfp-48'
  | 'rj45-4';

export interface Device {
  id: string;
  name: string;
  env: Environment;
  platform: Platform;
  role: DeviceRole;
  mgmt_ip: string;
  model: string;
  portCount: number;
  portKind: PortKind;
  /** true=reachable, false=unreachable, null=not yet polled (unknown). */
  reachable: boolean | null;
  /**
   * SSH login user (FreeBSD copy-chip). Optional; the UI defaults to `root`
   * when absent.
   */
  ssh_user?: string;
}

/**
 * Per-port service/protocol flags. Free-form: real drivers report what they
 * model (often nothing — pica8/NETCONF has no per-port flags, so this is {} and
 * the panel's Services section hides). Keyed by lowercase name -> enabled.
 */
export type PortServices = Record<string, boolean>;

export interface Port {
  device_id: string;
  name: string;
  index: number;
  state: PortState;
  admin_up: boolean;
  link_up: boolean;
  speed_mbps: number | null;
  duplex: 'full' | 'half' | null;
  mac: string | null;
  mtu: number;
  untagged_vlan: number;
  tagged_vlans: number[];
  description: string;
  host_model: string;
  bmc_ip: string;
  notes: string;
  services: PortServices;
  /** 0..1 — drives the LED pulse intensity in 3D and 2D. */
  traffic: number;
  /** Epoch ms of the last change. */
  last_change: number;
  /**
   * Optional LLDP neighbor list, populated by drivers that support LLDP. When
   * undefined or empty, the UI hides the Neighbor row entirely.
   */
  neighbors?: Neighbor[];
}

export type LinkKind = 'fiber' | 'copper';
export type TopologyLink = readonly [from: string, to: string, kind: LinkKind];

/**
 * Lifecycle states, matching the backend's `ChangeRequestStatus`. `applying`,
 * `awaiting_confirm` and `reverted` are the commit-confirm transient states the
 * real apply flow walks through; the mock client only ever emits the terminal
 * subset.
 */
export type ChangeRequestStatus =
  | 'pending'
  | 'approved'
  | 'applying'
  | 'awaiting_confirm'
  | 'applied'
  | 'rejected'
  | 'reverted'
  | 'failed';

export interface RequestedChanges {
  untagged_vlan?: number;
  tagged_vlans?: number[];
  host_model?: string;
  bmc_ip?: string;
  notes?: string;
}

export interface ChangeRequest {
  id: string;
  device_id: string;
  port_name: string;
  requested_by: string;
  requested_changes: RequestedChanges;
  reason: string;
  status: ChangeRequestStatus;
  reviewer_id: string | null;
  reviewer_comment: string;
  created_at: number;
  reviewed_at: number | null;
  applied_at: number | null;
}

export interface AuditEntry {
  id: string;
  device_id: string;
  port_name: string;
  user: string;
  action: string;
  ago_minutes: number;
  summary: string;
}

export interface User {
  username: string;
  role: UserRole;
  name: string;
}

export interface PortMap {
  [deviceId: string]: Port[];
}

/** Live system snapshot (protocols / mgmt services / MAC table). */
export interface MacEntry {
  vlan: number | null;
  mac: string;
  interface: string;
  type: string;
  age: string | null;
}

export interface ProtocolStatus {
  name: string;
  enabled: boolean;
  detail: string;
  params: [string, string][];
  has_detail: boolean;
}

export interface ProtocolTable {
  title: string;
  columns: string[];
  rows: string[][];
}

export interface ProtocolDetail {
  slug: string;
  tables: ProtocolTable[];
  error: string | null;
}

export interface VlanInfo {
  vlan_id: number;
  name: string;
  description: string;
  l3_interface: string;
  port_count: number;
}

export interface L3Interface {
  name: string;
  kind: string; // "management" | "svi" | "aggregated"
  ipv4: string;
  gateway: string;
  mtu: number | null;
  enabled: boolean;
  detail: string;
}

export interface MgmtService {
  name: string;
  enabled: boolean;
  port: number | null;
  detail: string;
  /** false = a known service that is absent from the device config. */
  configured: boolean;
}

export interface DeviceFacts {
  model: string;
  os_version: string;
  serial: string;
  uptime: string;
  license: string;
  base_mac: string;
  released: string;
}

export interface SystemInfo {
  facts: DeviceFacts;
  protocols: ProtocolStatus[];
  services: MgmtService[];
  mac_table: MacEntry[];
  mac_supported: boolean;
}

/**
 * Onboarding wizard — what the registry surfaces about a platform driver.
 * Mirrors `DriverCapabilities` from `principal-engineering.md` D5/D8.
 */
export type AuthMethod =
  | 'password'
  | 'ssh_key'
  | 'api_token'
  | 'snmp_v2c_community'
  | 'snmp_v3';

/**
 * Granular driver identifier returned by `GET /api/platforms`. For the current
 * backend the driver IDs map 1:1 onto the broad `Platform` category. The type
 * is kept distinct so the contract can grow OS-specific drivers later without
 * a UI-wide rename.
 */
export type PlatformId = 'arista' | 'cisco' | 'pica8' | 'freebsd' | 'mock';

export interface PlatformCapabilities {
  writable: boolean;
  supports_commit_confirm: boolean;
  native_api_available: boolean;
  /** SwOS-driven addition: device exposes a readable SNMP surface. */
  supports_snmp_read: boolean;
  /** Driver can return LLDP neighbors via its primary transport. */
  supports_lldp: boolean;
  max_concurrency: number;
  auth_methods: AuthMethod[];
}

export interface PlatformRegistryEntry {
  /** Granular driver ID — `mikrotik_routeros`, `mikrotik_swos`, etc. */
  platform_id: PlatformId;
  /** Broad platform category used by `Device.platform`. */
  platform: Platform;
  /** Human-readable label shown in the onboarding wizard. */
  display_name: string;
  description: string;
  defaultPort: number;
  capabilities: PlatformCapabilities;
  /**
   * Template for the vendor's own web UI. `{mgmt_ip}` is the only placeholder.
   * `null` means there is no web UI (FreeBSD); UI surfaces an SSH chip instead.
   */
  web_ui_url_template: string | null;
  /** Optional short note shown alongside the platform in the wizard. */
  notes?: string;
}

export interface OnboardingDraft {
  platform_id: PlatformId | null;
  /** Broad category, derived from the selected platform_id. */
  platform: Platform | null;
  name: string;
  env: Environment;
  role: DeviceRole;
  mgmt_ip: string;
  port: number;
  prefer_native_api: boolean;
  auth_method: AuthMethod;
  username: string;
  password: string;
  ssh_key: string;
  api_token: string;
  /** SNMP v2c community string (used when auth_method === 'snmp_v2c_community'). */
  snmp_community: string;
}

/**
 * Single LLDP neighbor as normalized by the driver layer (`_lib/lldp.py`).
 * Display-only — Northbound never uses this to auto-onboard.
 */
export interface Neighbor {
  chassis_id: string;
  port_id: string;
  system_name: string | null;
  system_description?: string | null;
}

/**
 * API envelope. The real backend uses Pydantic + OpenAPI; the mock client
 * matches this shape so the swap is mechanical. `meta` is only present on
 * paginated responses.
 */
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  meta?: {
    total: number;
    page: number;
    limit: number;
  };
}

/**
 * Live cache snapshot returned from `GET /devices/{id}/ports`. Matches the
 * "30s TTL with explicit refresh" semantics from D2.
 */
export interface PortListSnapshot {
  device_id: string;
  ports: Port[];
  fetched_at: number;
  cache_ttl_seconds: number;
}

/**
 * Auth payload persisted by the auth store. The real backend's
 * `POST /api/auth/login` returns `{ access_token, role, username }`; the mock
 * client mints a fake token but the shape is identical so the store and
 * components don't branch on which client is active.
 */
export interface AuthSession {
  access_token: string;
  username: string;
  role: UserRole;
}
