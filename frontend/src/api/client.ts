/**
 * Northbound API client (mock).
 *
 * Every operation that would be a network call in production is implemented
 * here against in-memory fixtures with a small synthetic delay. The function
 * surface — argument shapes, return types, error conventions — matches the
 * REST contract in `principal-engineering.md` so swapping to a real client
 * (likely a thin `fetch` wrapper around generated openapi-typescript types)
 * is mechanical.
 *
 * To swap implementations later:
 *   1. Replace the body of each function with a `fetch(url, ...)` call.
 *   2. Drop in the generated TS types from `openapi-typescript`.
 *   3. Remove the in-session mutation helpers at the bottom of this file —
 *      React Query already handles cache invalidation via `queryKey`s.
 */

import type {
  AuditEntry,
  ChangeRequest,
  ChangeRequestStatus,
  Device,
  Environment,
  OnboardingDraft,
  Platform,
  PlatformRegistryEntry,
  Port,
  PortListSnapshot,
  PortMap,
  User,
} from '@/types';
import type {
  ConfirmOnboardResult,
  CreateRequestInput,
  DiscoverResult,
  LoginResult,
  TestConnectionResult,
} from './client.types';
import {
  AUDIT,
  CHANGE_REQUESTS,
  DEVICES,
  LINKS,
  PORTS,
  USERS,
} from '@/mocks/fixtures';
import { PLATFORM_REGISTRY, findPlatform } from '@/mocks/registry';

export type {
  ConfirmOnboardResult,
  CreateRequestInput,
  DiscoverResult,
  LoginResult,
  TestConnectionResult,
};

const NETWORK_DELAY_MS = 280;

function delay(ms: number = NETWORK_DELAY_MS): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * In-session mutable state.
 *
 * Mocks need somewhere to apply optimistic updates so the rest of the app
 * sees consistent reads after writes. Real backend will own this on the DB
 * side; we'll delete this layer entirely when we cut over.
 */
interface MutableState {
  ports: PortMap;
  requests: ChangeRequest[];
  devices: Device[];
}

const state: MutableState = {
  ports: structuredClone(PORTS),
  requests: structuredClone(CHANGE_REQUESTS) as ChangeRequest[],
  devices: structuredClone(DEVICES) as Device[],
};

/** Force a fresh snapshot — used by tests that want a clean slate. */
export function __resetMockState(): void {
  state.ports = structuredClone(PORTS);
  state.requests = structuredClone(CHANGE_REQUESTS) as ChangeRequest[];
  state.devices = structuredClone(DEVICES) as Device[];
}

/* -------------------------------------------------------------------------
 * Auth
 * ------------------------------------------------------------------------- */

export async function login(username: string, _password: string): Promise<LoginResult> {
  await delay(220);
  const user = USERS.find((u) => u.username === username) ?? USERS[0]!;
  return { user, access_token: `mock-jwt-${user.username}` };
}

export async function getCurrentUser(username?: string): Promise<User> {
  await delay(80);
  const user = USERS.find((u) => u.username === username) ?? USERS[0]!;
  return user;
}

export async function logout(): Promise<void> {
  await delay(40);
}

export async function listUsers(): Promise<User[]> {
  await delay(120);
  return [...USERS];
}

/* -------------------------------------------------------------------------
 * Platforms (onboarding)
 * ------------------------------------------------------------------------- */

export async function listPlatforms(): Promise<readonly PlatformRegistryEntry[]> {
  await delay(60);
  return PLATFORM_REGISTRY;
}

/* -------------------------------------------------------------------------
 * Devices
 * ------------------------------------------------------------------------- */

export async function listDevices(env?: Environment): Promise<Device[]> {
  await delay();
  return env ? state.devices.filter((d) => d.env === env) : [...state.devices];
}

export async function getDevice(id: string): Promise<Device> {
  await delay(120);
  const device = state.devices.find((d) => d.id === id);
  if (!device) throw new Error(`Device ${id} not found`);
  return device;
}

export async function listLinks(env?: Environment): Promise<typeof LINKS> {
  await delay(60);
  if (!env) return LINKS;
  return LINKS.filter(([a]) => state.devices.find((d) => d.id === a)?.env === env);
}

/* -------------------------------------------------------------------------
 * Ports
 * ------------------------------------------------------------------------- */

export async function listPortsForDevice(
  deviceId: string,
  options: { refresh?: boolean } = {},
): Promise<PortListSnapshot> {
  // The real endpoint honors `?refresh=true` — we just use it to vary the
  // delay so the spinner is visible.
  await delay(options.refresh ? 600 : 200);
  const ports = state.ports[deviceId];
  if (!ports) throw new Error(`No ports for device ${deviceId}`);
  return {
    device_id: deviceId,
    ports: [...ports],
    fetched_at: Date.now(),
    cache_ttl_seconds: 30,
  };
}

export async function listAllPorts(): Promise<PortMap> {
  await delay(80);
  return state.ports;
}

/** Used by the global search bar — no deduplication, leaves ranking to caller. */
export async function searchPorts(env: Environment, query: string): Promise<
  Array<{ device: Device; port: Port }>
> {
  await delay(80);
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const results: Array<{ device: Device; port: Port }> = [];
  for (const device of state.devices) {
    if (device.env !== env) continue;
    const ports = state.ports[device.id] ?? [];
    for (const port of ports) {
      if (
        port.name.toLowerCase().includes(q) ||
        port.description.toLowerCase().includes(q) ||
        String(port.untagged_vlan) === q ||
        port.host_model.toLowerCase().includes(q) ||
        port.bmc_ip.includes(q)
      ) {
        results.push({ device, port });
      }
    }
  }
  return results;
}

/* -------------------------------------------------------------------------
 * Change requests
 * ------------------------------------------------------------------------- */

export async function listRequests(filter?: {
  mine?: string;
  status?: ChangeRequestStatus;
}): Promise<ChangeRequest[]> {
  await delay(120);
  let list = [...state.requests];
  if (filter?.mine) list = list.filter((r) => r.requested_by === filter.mine);
  if (filter?.status) list = list.filter((r) => r.status === filter.status);
  return list;
}

export async function createRequest(input: CreateRequestInput): Promise<ChangeRequest> {
  await delay(280);
  const id = `r-${Math.random().toString(36).slice(2, 6)}`;
  const req: ChangeRequest = {
    id,
    device_id: input.device_id,
    port_name: input.port_name,
    requested_by: input.requested_by,
    requested_changes: input.requested_changes,
    reason: input.reason,
    status: 'pending',
    reviewer_id: null,
    reviewer_comment: '',
    created_at: Date.now(),
    reviewed_at: null,
    applied_at: null,
  };
  state.requests = [req, ...state.requests];
  return req;
}

export async function approveRequest(id: string, reviewer: string): Promise<ChangeRequest> {
  await delay(220);
  const idx = state.requests.findIndex((r) => r.id === id);
  if (idx < 0) throw new Error(`Request ${id} not found`);
  const updated: ChangeRequest = {
    ...state.requests[idx]!,
    status: 'approved',
    reviewer_id: reviewer,
    reviewed_at: Date.now(),
  };
  state.requests = state.requests.map((r) => (r.id === id ? updated : r));
  return updated;
}

export async function rejectRequest(
  id: string,
  reviewer: string,
  comment: string,
): Promise<ChangeRequest> {
  await delay(220);
  const idx = state.requests.findIndex((r) => r.id === id);
  if (idx < 0) throw new Error(`Request ${id} not found`);
  const updated: ChangeRequest = {
    ...state.requests[idx]!,
    status: 'rejected',
    reviewer_id: reviewer,
    reviewed_at: Date.now(),
    reviewer_comment: comment,
  };
  state.requests = state.requests.map((r) => (r.id === id ? updated : r));
  return updated;
}

/**
 * Apply flow — mocked. Real backend runs `backup → render → apply → confirm`
 * with platform-specific commit-confirm. Here we just mutate the in-memory
 * port and flip the request to 'applied' after a synthetic delay.
 */
export async function applyRequest(id: string, reviewer: string): Promise<ChangeRequest> {
  // First flip to approved so optimistic UI sees an in-flight state.
  await delay(120);
  const before = state.requests.find((r) => r.id === id);
  if (!before) throw new Error(`Request ${id} not found`);

  const approved: ChangeRequest = {
    ...before,
    status: 'approved',
    reviewer_id: reviewer,
    reviewed_at: Date.now(),
  };
  state.requests = state.requests.map((r) => (r.id === id ? approved : r));

  // Then push the change to the (mock) device.
  await delay(600);
  const ports = state.ports[before.device_id] ?? [];
  const portIdx = ports.findIndex((p) => p.name === before.port_name);
  if (portIdx >= 0) {
    const port = ports[portIdx]!;
    const change = before.requested_changes;
    const newVlan = change.untagged_vlan ?? port.untagged_vlan;
    const newTagged = change.tagged_vlans ?? port.tagged_vlans;
    const newHost = change.host_model ?? port.host_model;
    const newBmc = change.bmc_ip ?? port.bmc_ip;
    const newDescription =
      newVlan && newHost && newBmc
        ? `VLAN-${newVlan} | ${newHost} | ${newBmc}`
        : port.description;
    const updatedPort: Port = {
      ...port,
      untagged_vlan: newVlan,
      tagged_vlans: newTagged,
      host_model: newHost,
      bmc_ip: newBmc,
      notes: change.notes ?? port.notes,
      description: newDescription,
      last_change: Date.now(),
    };
    state.ports = {
      ...state.ports,
      [before.device_id]: ports.map((p, i) => (i === portIdx ? updatedPort : p)),
    };
  }

  const applied: ChangeRequest = {
    ...approved,
    status: 'applied',
    applied_at: Date.now(),
  };
  state.requests = state.requests.map((r) => (r.id === id ? applied : r));
  return applied;
}

/**
 * Confirm flow — mocked. Real backend resolves the commit-confirm timer to
 * make an applied change permanent. The mock already flips to 'applied' inside
 * {@link applyRequest}, so this is a no-op that just echoes current state.
 */
export async function confirmRequest(id: string): Promise<ChangeRequest> {
  await delay(120);
  const req = state.requests.find((r) => r.id === id);
  if (!req) throw new Error(`Request ${id} not found`);
  return req;
}

/* -------------------------------------------------------------------------
 * Audit
 * ------------------------------------------------------------------------- */

export async function listAudit(filter: {
  device_id?: string;
  port_name?: string;
} = {}): Promise<AuditEntry[]> {
  await delay(80);
  let list = [...AUDIT];
  if (filter.device_id) list = list.filter((a) => a.device_id === filter.device_id);
  if (filter.port_name) list = list.filter((a) => a.port_name === filter.port_name);
  return list;
}

/* -------------------------------------------------------------------------
 * Onboarding wizard
 * ------------------------------------------------------------------------- */

export async function testConnection(_draft: OnboardingDraft): Promise<TestConnectionResult> {
  await delay(900);
  return {
    ok: true,
    latency_ms: 12 + Math.floor(Math.random() * 30),
    message: 'Authenticated and reachable.',
  };
}

export async function discoverDevice(draft: OnboardingDraft): Promise<DiscoverResult> {
  await delay(1100);
  const platform: Platform = draft.platform ?? 'cisco';
  const sample =
    platform === 'pica8'
      ? ['te-1/1/1', 'te-1/1/2', 'te-1/1/3', 'te-1/1/4']
      : platform === 'freebsd'
        ? ['igb0', 'igb1', 'ix0', 'ix1']
        : ['Ethernet1', 'Ethernet2', 'Ethernet3', 'Ethernet4'];
  const portCount =
    platform === 'arista' ? 32 : platform === 'pica8' ? 48 : platform === 'freebsd' ? 4 : 24;
  const config_excerpt =
    platform === 'cisco'
      ? `interface Ethernet1\n  description VLAN-100\n  switchport access vlan 100`
      : platform === 'arista'
        ? `interface Ethernet1/1\n  description VLAN-100\n  switchport access vlan 100`
        : platform === 'pica8'
          ? `set interface te-1/1/1 description "VLAN-100"\nset vlans v100 interface te-1/1/1 untagged`
          : `# /etc/rc.conf\nifconfig_igb0="up"\nifconfig_igb0_100="inet 10.0.100.1/24"`;
  return { port_count: portCount, sample_ports: sample, config_excerpt };
}

export async function confirmOnboard(draft: OnboardingDraft): Promise<ConfirmOnboardResult> {
  await delay(700);
  if (!draft.platform_id) throw new Error('platform is required');
  const platform = findPlatform(draft.platform_id);
  if (!platform) throw new Error(`Unknown platform ${draft.platform_id}`);
  const id = `d-${draft.env}-${draft.name.toLowerCase().replace(/[^a-z0-9-]/g, '-')}`;
  const portKind = portKindForPlatform(platform.platform);
  const portCount =
    platform.platform === 'arista'
      ? 32
      : platform.platform === 'pica8'
        ? 48
        : platform.platform === 'freebsd'
          ? 4
          : 24;
  const device: Device = {
    id,
    name: draft.name,
    env: draft.env,
    platform: platform.platform,
    role: draft.role,
    mgmt_ip: draft.mgmt_ip,
    model: platform.display_name,
    portCount,
    portKind,
    reachable: true,
  };
  state.devices = [...state.devices, device];
  state.ports = { ...state.ports, [id]: seedPortsFor(device) };
  return { device, ports_seeded: portCount };
}

function portKindForPlatform(platform: Platform): Device['portKind'] {
  switch (platform) {
    case 'arista':
      return 'qsfp-32';
    case 'pica8':
      return 'sfp-48';
    case 'freebsd':
      return 'rj45-4';
    case 'cisco':
    case 'mock':
    default:
      return 'rj45-24-2sfp';
  }
}

function seedPortsFor(device: Device): Port[] {
  const out: Port[] = [];
  for (let i = 0; i < device.portCount; i++) {
    out.push({
      device_id: device.id,
      name:
        device.platform === 'arista'
          ? `Ethernet${i + 1}/1`
          : device.platform === 'pica8'
            ? `te-1/1/${i + 1}`
            : device.platform === 'freebsd'
              ? ['igb0', 'igb1', 'ix0', 'ix1'][i] ?? `igb${i}`
              : i < 24
                ? `Ethernet${i + 1}`
                : `Ethernet${i + 1}`,
      index: i,
      state: 'down',
      admin_up: true,
      link_up: false,
      speed_mbps: null,
      duplex: null,
      mac: null,
      mtu: 1500,
      untagged_vlan: 10,
      tagged_vlans: [],
      description: '',
      host_model: '',
      bmc_ip: '',
      notes: '',
      services: { lldp: true, stp: false, mstp: false, lacp: false, bgp: false, ospf: false, erspan: false },
      traffic: 0,
      last_change: Date.now(),
    });
  }
  return out;
}

/* -------------------------------------------------------------------------
 * Reference data
 * ------------------------------------------------------------------------- */
export { VLANS } from '@/mocks/fixtures';
