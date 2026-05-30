/**
 * Client-selector tests — confirms the offline-first default and that the
 * flag flips the active implementation. The selector reads `VITE_USE_MOCKS`
 * at module-load time, so each case stubs the env then re-imports the module
 * with a fresh registry.
 */

import { afterEach, describe, expect, test, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe('apiClient selector', () => {
  test('defaults to the mock client when VITE_USE_MOCKS is unset', async () => {
    vi.stubEnv('VITE_USE_MOCKS', '');
    vi.resetModules();
    const api = await import('./index');
    const mock = await import('./client');
    expect(api.USE_MOCKS).toBe(true);
    expect(api.apiClient.listDevices).toBe(mock.listDevices);
  });

  test('keeps mocks for any value other than the literal "false"', async () => {
    vi.stubEnv('VITE_USE_MOCKS', 'true');
    vi.resetModules();
    const api = await import('./index');
    expect(api.USE_MOCKS).toBe(true);
  });

  test('selects the real client when VITE_USE_MOCKS === "false"', async () => {
    vi.stubEnv('VITE_USE_MOCKS', 'false');
    vi.resetModules();
    const api = await import('./index');
    const real = await import('./realClient');
    expect(api.USE_MOCKS).toBe(false);
    expect(api.apiClient.listDevices).toBe(real.listDevices);
  });
});
