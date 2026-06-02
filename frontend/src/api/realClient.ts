/**
 * Northbound real API client.
 *
 * Implements the exact same function surface as the mock `client.ts`, but over
 * `fetch` against the FastAPI backend. The selector in `index.ts` chooses
 * between this and the mock at module load based on `VITE_USE_MOCKS`, so no
 * component or query hook changes call sites.
 *
 * Conventions:
 *   - `Authorization: Bearer <token>` from the auth store on every request.
 *   - 401 → clear the session and bounce to /login (the auth store + a hard
 *     redirect; React Router guard also covers the SPA-internal case).
 *   - Non-2xx → throw `ApiError { status, code?, message }` so TanStack Query
 *     surfaces a typed error.
 */

import type {
  AuditEntry,
  AuthMethod,
  ChangeRequest,
  ChangeRequestStatus,
  Device,
  Environment,
  OnboardingDraft,
  Port,
  PortListSnapshot,
  L3Interface,
  PortMap,
  ProtocolDetail,
  Site,
  SystemInfo,
  TopologyLink,
  VlanInfo,
  PlatformRegistryEntry,
  User,
} from '@/types';
import type { components } from './schema.gen';
import { ApiError } from './errors';
import { clearAuthSession, getAuthToken } from '@/store/auth';
import {
  mapAudit,
  mapDevice,
  mapPlatform,
  mapPort,
  mapRequest,
} from './mappers';
import type {
  CreateRequestInput,
  ConfirmOnboardResult,
  DiscoverResult,
  LoginResult,
  TestConnectionResult,
} from './client.types';

const API_BASE = import.meta.env.VITE_API_BASE ?? '';

type LoginResponse = components['schemas']['LoginResponse'];
type UserOut = components['schemas']['UserOut'];
type DeviceOut = components['schemas']['DeviceOut'];
type PortStateOut = components['schemas']['PortStateOut'];
type RequestOut = components['schemas']['RequestOut'];
type AuditEntryOut = components['schemas']['AuditEntryOut'];
type PlatformInfo = components['schemas']['PlatformInfo'];
type TestConnectionOut = components['schemas']['TestConnectionOut'];
type DiscoverOut = components['schemas']['DiscoverOut'];

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  /** Skip the Authorization header (login only). */
  anonymous?: boolean;
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }
  // Preserve relative same-origin form when API_BASE is empty.
  return API_BASE ? url.toString() : `${url.pathname}${url.search}`;
}

async function parseError(res: Response): Promise<ApiError> {
  let message = res.statusText || `HTTP ${res.status}`;
  let code: string | undefined;
  try {
    const data = (await res.json()) as { detail?: unknown; code?: string };
    if (typeof data.detail === 'string') message = data.detail;
    else if (Array.isArray(data.detail) && data.detail.length > 0) {
      const first = data.detail[0] as { msg?: string };
      if (first?.msg) message = first.msg;
    }
    if (typeof data.code === 'string') code = data.code;
  } catch {
    /* non-JSON error body — keep the status-derived message */
  }
  return new ApiError(res.status, message, code);
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, anonymous } = options;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (!anonymous) {
    const token = getAuthToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  let res: Response;
  try {
    res = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    throw new ApiError(0, err instanceof Error ? err.message : 'Network error');
  }

  if (res.status === 401) {
    clearAuthSession();
    if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
      window.location.assign('/login');
    }
    throw new ApiError(401, 'Session expired — please sign in again.');
  }

  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;

  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/* -------------------------------------------------------------------------
 * Auth
 * ------------------------------------------------------------------------- */

export async function login(username: string, password: string): Promise<LoginResult> {
  const res = await request<LoginResponse>('/api/auth/login', {
    method: 'POST',
    body: { username, password },
    anonymous: true,
  });
  return {
    access_token: res.access_token,
    user: { username: res.username, role: res.role, name: res.username },
  };
}

export async function getCurrentUser(_username?: string): Promise<User> {
  const me = await request<UserOut>('/api/users/me');
  return { username: me.username, role: me.role, name: me.username };
}

export async function logout(): Promise<void> {
  try {
    await request<void>('/api/auth/logout', { method: 'POST' });
  } catch {
    /* best-effort — the store is cleared regardless */
  }
}

export async function listUsers(): Promise<User[]> {
  const users = await request<UserOut[]>('/api/users');
  return users.map((u) => ({ username: u.username, role: u.role, name: u.username }));
}

/* -------------------------------------------------------------------------
 * Sites (the runtime-managed location/environment catalog)
 * ------------------------------------------------------------------------- */

interface SiteOut {
  id: string;
  slug: string;
  name: string;
  device_count: number;
}

function mapSite(s: SiteOut): Site {
  return { id: s.id, slug: s.slug, name: s.name, deviceCount: s.device_count };
}

export async function listSites(): Promise<Site[]> {
  const sites = await request<SiteOut[]>('/api/sites');
  return sites.map(mapSite);
}

export async function createSite(input: { slug: string; name: string }): Promise<Site> {
  const site = await request<SiteOut>('/api/sites', { method: 'POST', body: input });
  return mapSite(site);
}

export async function renameSite(id: string, name: string): Promise<Site> {
  const site = await request<SiteOut>(`/api/sites/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: { name },
  });
  return mapSite(site);
}

export async function deleteSite(id: string): Promise<void> {
  await request<void>(`/api/sites/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

/* -------------------------------------------------------------------------
 * Platforms
 * ------------------------------------------------------------------------- */

export async function listPlatforms(): Promise<readonly PlatformRegistryEntry[]> {
  const platforms = await request<PlatformInfo[]>('/api/platforms');
  return platforms.map(mapPlatform);
}

/* -------------------------------------------------------------------------
 * Devices
 * ------------------------------------------------------------------------- */

export async function listDevices(env?: Environment): Promise<Device[]> {
  const devices = await request<DeviceOut[]>('/api/devices', {
    query: env ? { environment: env } : undefined,
  });
  return devices.map((d) => mapDevice(d));
}

export async function getDevice(id: string): Promise<Device> {
  const d = await request<DeviceOut>(`/api/devices/${encodeURIComponent(id)}`);
  return mapDevice(d);
}

export async function getSystemInfo(id: string): Promise<SystemInfo> {
  return request<SystemInfo>(`/api/devices/${encodeURIComponent(id)}/system`);
}

export async function getProtocolDetail(id: string, slug: string): Promise<ProtocolDetail> {
  return request<ProtocolDetail>(
    `/api/devices/${encodeURIComponent(id)}/protocols/${encodeURIComponent(slug)}`,
  );
}

export async function getVlans(id: string): Promise<VlanInfo[]> {
  return request<VlanInfo[]>(`/api/devices/${encodeURIComponent(id)}/vlans`);
}

export async function getL3Interfaces(id: string): Promise<L3Interface[]> {
  return request<L3Interface[]>(`/api/devices/${encodeURIComponent(id)}/l3-interfaces`);
}

export async function listLinks(_env?: Environment): Promise<readonly TopologyLink[]> {
  // The backend does not model topology links; the 3D topology view falls back
  // to an empty link set when running against the real API.
  return [];
}

/* -------------------------------------------------------------------------
 * Ports
 * ------------------------------------------------------------------------- */

export async function listPortsForDevice(
  deviceId: string,
  options: { refresh?: boolean } = {},
): Promise<PortListSnapshot> {
  // Backend GET /api/devices/{id}/ports returns a flat PortStateOut[] (see
  // backend api/ports.py response_model=list[PortStateOut]); it is NOT the
  // single-port PortDetailOut shape, so each element maps directly.
  const ports = await request<PortStateOut[]>(
    `/api/devices/${encodeURIComponent(deviceId)}/ports`,
    { query: options.refresh ? { refresh: true } : undefined },
  );
  return {
    device_id: deviceId,
    ports: ports.map((p, i) => mapPort(p, deviceId, i)),
    fetched_at: Date.now(),
    cache_ttl_seconds: 30,
  };
}

export async function updatePortMetadata(
  deviceId: string,
  portName: string,
  patch: { host_model?: string; bmc_ip?: string; notes?: string },
): Promise<Port> {
  const p = await request<PortStateOut>(
    `/api/devices/${encodeURIComponent(deviceId)}/ports/${encodeURIComponent(portName)}`,
    { method: 'PATCH', body: patch },
  );
  return mapPort(p, deviceId, 0);
}

export async function listAllPorts(): Promise<PortMap> {
  const devices = await listDevices();
  const map: PortMap = {};
  await Promise.all(
    devices.map(async (d) => {
      try {
        const snap = await listPortsForDevice(d.id);
        map[d.id] = snap.ports;
      } catch (err) {
        // A single device failing to poll must not collapse the whole map, but
        // the failure must be surfaced, not silently swallowed.
        console.error(`listAllPorts: failed to load ports for device ${d.id}`, err);
        map[d.id] = [];
      }
    }),
  );
  return map;
}

export async function searchPorts(
  env: Environment,
  query: string,
): Promise<Array<{ device: Device; port: Port }>> {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const devices = await listDevices(env);
  const results: Array<{ device: Device; port: Port }> = [];
  await Promise.all(
    devices.map(async (device) => {
      const snap = await listPortsForDevice(device.id);
      for (const port of snap.ports) {
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
    }),
  );
  return results;
}

/* -------------------------------------------------------------------------
 * Change requests
 * ------------------------------------------------------------------------- */

export async function listRequests(filter?: {
  mine?: string;
  status?: ChangeRequestStatus;
}): Promise<ChangeRequest[]> {
  const requests = await request<RequestOut[]>('/api/requests', {
    query: {
      mine: filter?.mine ? true : undefined,
      request_status: filter?.status,
    },
  });
  return requests.map(mapRequest);
}

export async function createRequest(input: CreateRequestInput): Promise<ChangeRequest> {
  const req = await request<RequestOut>('/api/requests', {
    method: 'POST',
    body: {
      device_id: input.device_id,
      port_name: input.port_name,
      requested_changes: input.requested_changes,
      reason: input.reason,
    },
  });
  return mapRequest(req);
}

export async function approveRequest(id: string, _reviewer: string): Promise<ChangeRequest> {
  const req = await request<RequestOut>(
    `/api/requests/${encodeURIComponent(id)}/approve`,
    { method: 'POST' },
  );
  return mapRequest(req);
}

export async function rejectRequest(
  id: string,
  _reviewer: string,
  comment: string,
): Promise<ChangeRequest> {
  const req = await request<RequestOut>(
    `/api/requests/${encodeURIComponent(id)}/reject`,
    { method: 'POST', body: { comment } },
  );
  return mapRequest(req);
}

export async function applyRequest(id: string, _reviewer: string): Promise<ChangeRequest> {
  const req = await request<RequestOut>(
    `/api/requests/${encodeURIComponent(id)}/apply`,
    { method: 'POST' },
  );
  return mapRequest(req);
}

export async function confirmRequest(id: string): Promise<ChangeRequest> {
  const req = await request<RequestOut>(
    `/api/requests/${encodeURIComponent(id)}/confirm`,
    { method: 'POST' },
  );
  return mapRequest(req);
}

/* -------------------------------------------------------------------------
 * Audit
 * ------------------------------------------------------------------------- */

export async function listAudit(
  filter: { device_id?: string; port_name?: string } = {},
): Promise<AuditEntry[]> {
  const entries = await request<AuditEntryOut[]>('/api/audit', {
    query: { device_id: filter.device_id, port: filter.port_name },
  });
  return entries.map(mapAudit);
}

/* -------------------------------------------------------------------------
 * Onboarding wizard
 * ------------------------------------------------------------------------- */

function credentialsFromDraft(draft: OnboardingDraft): Record<string, string | undefined> {
  const method: AuthMethod = draft.auth_method;
  return {
    username: method === 'snmp_v2c_community' ? undefined : draft.username || undefined,
    password: method === 'password' || method === 'snmp_v3' ? draft.password || undefined : undefined,
    ssh_private_key: method === 'ssh_key' ? draft.ssh_key || undefined : undefined,
    api_token: method === 'api_token' ? draft.api_token || undefined : undefined,
    snmp_community: method === 'snmp_v2c_community' ? draft.snmp_community || undefined : undefined,
  };
}

function connectionBody(draft: OnboardingDraft): Record<string, unknown> {
  return {
    platform_id: draft.platform_id,
    mgmt_ip: draft.mgmt_ip,
    port: draft.port || undefined,
    prefer_native_api: draft.prefer_native_api,
    credentials: credentialsFromDraft(draft),
  };
}

export async function testConnection(draft: OnboardingDraft): Promise<TestConnectionResult> {
  const res = await request<TestConnectionOut>('/api/devices/test-connection', {
    method: 'POST',
    body: connectionBody(draft),
  });
  return {
    ok: res.ok,
    latency_ms: Math.round(res.latency_ms),
    message: res.ok
      ? `Authenticated and reachable${res.platform_version ? ` (${res.platform_version})` : ''}.`
      : res.error ?? 'Connection failed.',
  };
}

export async function discoverDevice(draft: OnboardingDraft): Promise<DiscoverResult> {
  const res = await request<DiscoverOut>('/api/devices/discover', {
    method: 'POST',
    body: connectionBody(draft),
  });
  const ports = res.ports ?? [];
  return {
    port_count: ports.length,
    sample_ports: ports.slice(0, 4).map((p) => p.name),
    config_excerpt: res.running_config,
  };
}

export async function confirmOnboard(draft: OnboardingDraft): Promise<ConfirmOnboardResult> {
  if (!draft.platform_id) throw new ApiError(400, 'platform is required');
  const created = await request<DeviceOut>('/api/devices', {
    method: 'POST',
    body: {
      name: draft.name,
      environment: draft.env,
      role: draft.role,
      platform_id: draft.platform_id,
      mgmt_ip: draft.mgmt_ip,
      port: draft.port || undefined,
      ssh_user: draft.username || undefined,
      prefer_native_api: draft.prefer_native_api,
      credentials: credentialsFromDraft(draft),
    },
  });
  let portCount = 0;
  try {
    const snap = await listPortsForDevice(created.id);
    portCount = snap.ports.length;
  } catch (err: unknown) {
    // Expected best-effort: the device is created but ports may not be
    // pollable on the first beat. Report zero, but log so a persistent
    // seeding failure is diagnosable rather than silently hidden.
    console.error(`onboardDevice: initial port poll failed for ${created.id}`, err);
  }
  return { device: mapDevice(created, portCount), ports_seeded: portCount };
}

/* -------------------------------------------------------------------------
 * Reference data
 * ------------------------------------------------------------------------- */
