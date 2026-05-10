/**
 * Northbound — canonical types
 *
 * These mirror `supporting material/data.jsx` and the v1 backend contract
 * described in `principal-engineering.md`. The mock API client and the future
 * real client both produce values of these shapes; UI components consume them
 * unchanged.
 */

export type Environment = 'lab' | 'dc';
export type Platform = 'mikrotik' | 'arista' | 'pica8' | 'freebsd';
export type DeviceRole = 'leaf' | 'spine' | 'router' | 'vpn';
export type UserRole = 'admin' | 'requester';
export type PortState = 'up' | 'down' | 'disabled';

/**
 * Port physical layout — drives 3D rendering and 2D card density.
 *
 * - `rj45-24-2sfp`  → 24× RJ45 in 2 rows of 12 + 2× SFP+ on the right
 * - `sfp-5`         → 5× SFP+ inline (MikroTik spine)
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
  reachable: boolean;
}

export interface PortServices {
  lldp: boolean;
  stp: boolean;
  mstp: boolean;
  lacp: boolean;
  bgp: boolean;
  ospf: boolean;
  erspan: boolean;
}

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
}

export type LinkKind = 'fiber' | 'copper';
export type TopologyLink = readonly [from: string, to: string, kind: LinkKind];

export type ChangeRequestStatus =
  | 'pending'
  | 'approved'
  | 'applied'
  | 'rejected'
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

/**
 * Onboarding wizard — what the registry surfaces about a platform driver.
 * Mirrors `DriverCapabilities` from `principal-engineering.md` D5/D8.
 */
export type AuthKind = 'password' | 'ssh_key' | 'api_token';

export interface PlatformCapabilities {
  writable: boolean;
  supports_commit_confirm: boolean;
  native_api_available: boolean;
  max_concurrency: number;
  auth_kinds: AuthKind[];
}

export interface PlatformRegistryEntry {
  platform: Platform;
  label: string;
  description: string;
  defaultPort: number;
  capabilities: PlatformCapabilities;
}

export interface OnboardingDraft {
  platform: Platform | null;
  name: string;
  env: Environment;
  role: DeviceRole;
  mgmt_ip: string;
  port: number;
  prefer_native_api: boolean;
  auth_kind: AuthKind;
  username: string;
  password: string;
  ssh_key: string;
  api_token: string;
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
