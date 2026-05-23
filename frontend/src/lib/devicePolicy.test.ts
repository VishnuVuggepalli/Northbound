/**
 * devicePolicy unit tests — truth table for `isWriteLocked` plus a couple of
 * `vendorWebUiUrl` happy-path checks. The matrix mirrors the per-platform
 * capability table in `principal-engineering.md`.
 */

import { describe, expect, test } from 'vitest';
import { isWriteLocked, vendorWebUiUrl, findPlatformForDevice } from './devicePolicy';
import { PLATFORM_REGISTRY, findPlatform } from '@/mocks/registry';
import type { Device, DeviceRole, PlatformRegistryEntry } from '@/types';

const routerOs = findPlatform('mikrotik_routeros')!;
const swos = findPlatform('mikrotik_swos')!;
const arista = findPlatform('arista')!;
const freebsd = findPlatform('freebsd')!;

function dev(role: DeviceRole, overrides: Partial<Device> = {}): Device {
  return {
    id: 'd-test',
    name: 'test',
    env: 'lab',
    platform: 'mikrotik',
    role,
    mgmt_ip: '10.10.0.99',
    model: 'CRS326',
    portCount: 24,
    portKind: 'rj45-24-2sfp',
    reachable: true,
    ...overrides,
  };
}

describe('isWriteLocked', () => {
  test('returns true for router devices regardless of platform', () => {
    expect(isWriteLocked(dev('router'), arista)).toBe(true);
  });

  test('returns true for vpn devices regardless of platform', () => {
    expect(isWriteLocked(dev('vpn'), freebsd)).toBe(true);
  });

  test('returns true on writable=false platform (SwOS)', () => {
    expect(isWriteLocked(dev('leaf'), swos)).toBe(true);
  });

  test('returns true on writable=false platform (FreeBSD leaf — hypothetical)', () => {
    expect(isWriteLocked(dev('leaf'), freebsd)).toBe(true);
  });

  test('returns false for writable platform leaf', () => {
    expect(isWriteLocked(dev('leaf'), routerOs)).toBe(false);
    expect(isWriteLocked(dev('leaf'), arista)).toBe(false);
  });

  test('returns false for writable platform spine', () => {
    expect(isWriteLocked(dev('spine'), routerOs)).toBe(false);
  });

  test('returns false when platform is null and role is writable', () => {
    expect(isWriteLocked(dev('leaf'), null)).toBe(false);
  });

  test('still locks router when platform is null', () => {
    expect(isWriteLocked(dev('router'), null)).toBe(true);
  });
});

describe('vendorWebUiUrl', () => {
  test('substitutes {mgmt_ip} for RouterOS', () => {
    const url = vendorWebUiUrl(dev('leaf', { mgmt_ip: '10.10.0.11' }), routerOs);
    expect(url).toBe('http://10.10.0.11/webfig/');
  });

  test('returns null for FreeBSD (no web UI)', () => {
    expect(vendorWebUiUrl(dev('router', { mgmt_ip: '10.10.0.1' }), freebsd)).toBeNull();
  });

  test('returns null for missing platform', () => {
    expect(
      vendorWebUiUrl(dev('leaf'), null as unknown as PlatformRegistryEntry | null),
    ).toBeNull();
  });

  test('uses HTTPS template for Arista', () => {
    expect(vendorWebUiUrl(dev('leaf', { mgmt_ip: '10.20.0.11' }), arista)).toBe(
      'https://10.20.0.11/',
    );
  });
});

describe('findPlatformForDevice', () => {
  test('disambiguates SwOS from RouterOS via model regex', () => {
    const swosDevice = dev('leaf', { model: 'CRS112-8G-4S (SwOS)' });
    const got = findPlatformForDevice(swosDevice, PLATFORM_REGISTRY);
    expect(got?.platform_id).toBe('mikrotik_swos');
  });

  test('defaults MikroTik devices to RouterOS when model has no SwOS marker', () => {
    const routerOsDevice = dev('leaf', { model: 'CRS326-24G-2S+' });
    const got = findPlatformForDevice(routerOsDevice, PLATFORM_REGISTRY);
    expect(got?.platform_id).toBe('mikrotik_routeros');
  });

  test('maps non-MikroTik platforms 1:1', () => {
    const aristaDev = dev('leaf', { platform: 'arista', model: '7050X3' });
    expect(findPlatformForDevice(aristaDev, PLATFORM_REGISTRY)?.platform_id).toBe('arista');
  });
});
