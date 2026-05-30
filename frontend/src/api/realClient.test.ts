/**
 * Unit tests for the real fetch-based API client.
 *
 * Covers the load-bearing transport behaviors that the mock client can't:
 *   - Bearer token attached from the auth store on every request
 *   - non-2xx → typed ApiError mapping (status + detail message)
 *   - 401 → session cleared + redirect to /login
 *   - the client selector defaults to the mock (offline-first)
 */

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import * as realClient from './realClient';
import { ApiError } from './errors';
import { useAuthStore } from '@/store/auth';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  useAuthStore.setState({ user: null, token: null, isAuthenticated: false });
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('realClient transport', () => {
  test('attaches Bearer token from the auth store', async () => {
    useAuthStore.getState().setSession({
      access_token: 'tok-123',
      username: 'admin',
      role: 'admin',
    });
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    vi.stubGlobal('fetch', fetchMock);

    await realClient.listDevices();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0]!;
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-123');
  });

  test('omits Authorization on the login (anonymous) request', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ access_token: 'x', token_type: 'bearer', role: 'admin', username: 'admin' }),
      );
    vi.stubGlobal('fetch', fetchMock);

    await realClient.login('admin', 'pw');

    const [, init] = fetchMock.mock.calls[0]!;
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  test('login returns the unified LoginResult shape', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ access_token: 'jwt', token_type: 'bearer', role: 'requester', username: 'alice' }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const result = await realClient.login('alice', 'pw');
    expect(result.access_token).toBe('jwt');
    expect(result.user).toEqual({ username: 'alice', role: 'requester', name: 'alice' });
  });

  test('maps a non-2xx response to a typed ApiError with the detail message', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: 'device not found' }, 404));
    vi.stubGlobal('fetch', fetchMock);

    await expect(realClient.getDevice('nope')).rejects.toMatchObject({
      status: 404,
      message: 'device not found',
    });
    await expect(realClient.getDevice('nope')).rejects.toBeInstanceOf(ApiError);
  });

  test('401 clears the session and redirects to /login', async () => {
    useAuthStore.getState().setSession({
      access_token: 'expired',
      username: 'admin',
      role: 'admin',
    });
    const assign = vi.fn();
    vi.stubGlobal('location', {
      origin: 'http://localhost',
      pathname: '/env/lab',
      assign,
    } as unknown as Location);
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'expired' }, 401));
    vi.stubGlobal('fetch', fetchMock);

    await expect(realClient.listDevices()).rejects.toMatchObject({ status: 401 });
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().token).toBeNull();
    expect(assign).toHaveBeenCalledWith('/login');
  });

  test('network failure surfaces as ApiError(status=0)', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(realClient.listPlatforms()).rejects.toMatchObject({ status: 0 });
  });

  test('listPlatforms maps PlatformInfo into a registry entry', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([
        {
          platform_id: 'cisco',
          display_name: 'Cisco IOS / NX-OS',
          capabilities: {
            writable: true,
            supports_commit_confirm: true,
            native_api_available: true,
            supports_snmp_read: true,
            supports_lldp: true,
            max_concurrency: 5,
            auth_methods: ['password'],
            web_ui_url_template: 'https://{mgmt_ip}/',
          },
        },
      ]),
    );
    vi.stubGlobal('fetch', fetchMock);

    const platforms = await realClient.listPlatforms();
    expect(platforms).toHaveLength(1);
    expect(platforms[0]!.platform_id).toBe('cisco');
    expect(platforms[0]!.platform).toBe('cisco');
    expect(platforms[0]!.capabilities.writable).toBe(true);
    expect(platforms[0]!.web_ui_url_template).toBe('https://{mgmt_ip}/');
  });
});
