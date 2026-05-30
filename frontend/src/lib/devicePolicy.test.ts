/**
 * devicePolicy unit tests — truth table for `isWriteLocked` plus a couple of
 * `vendorWebUiUrl` happy-path checks. The matrix mirrors the per-platform
 * capability table in `principal-engineering.md`.
 */

import { describe, expect, test } from 'vitest';
import { isWriteLocked, vendorWebUiUrl, findPlatformForDevice } from './devicePolicy';
import { PLATFORM_REGISTRY, findPlatform } from '@/mocks/registry';
import type { Device, DeviceRole, PlatformRegistryEntry } from '@/types';

const cisco = findPlatform('cisco')!;
const arista = findPlatform('arista')!;
const freebsd = findPlatform('freebsd')!;

function dev(role: DeviceRole, overrides: Partial<Device> = {}): Device {
  return {
    id: 'd-test',
    name: 'test',
    env: 'lab',
    platform: 'cisco',
    role,
    mgmt_ip: '10.10.0.99',
    model: 'Catalyst 9300-24T',
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

  test('returns true on writable=false platform (FreeBSD leaf — hypothetical)', () => {
    expect(isWriteLocked(dev('leaf'), freebsd)).toBe(true);
  });

  test('returns false for writable platform leaf', () => {
    expect(isWriteLocked(dev('leaf'), cisco)).toBe(false);
    expect(isWriteLocked(dev('leaf'), arista)).toBe(false);
  });

  test('returns false for writable platform spine', () => {
    expect(isWriteLocked(dev('spine'), cisco)).toBe(false);
  });

  test('returns false when platform is null and role is writable', () => {
    expect(isWriteLocked(dev('leaf'), null)).toBe(false);
  });

  test('still locks router when platform is null', () => {
    expect(isWriteLocked(dev('router'), null)).toBe(true);
  });
});

describe('vendorWebUiUrl', () => {
  test('substitutes {mgmt_ip} for Cisco', () => {
    const url = vendorWebUiUrl(dev('leaf', { mgmt_ip: '10.10.0.11' }), cisco);
    expect(url).toBe('https://10.10.0.11/');
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
  test('maps Cisco devices 1:1', () => {
    const ciscoDev = dev('leaf', { platform: 'cisco', model: 'Catalyst 9300-24T' });
    expect(findPlatformForDevice(ciscoDev, PLATFORM_REGISTRY)?.platform_id).toBe('cisco');
  });

  test('maps Arista platforms 1:1', () => {
    const aristaDev = dev('leaf', { platform: 'arista', model: '7050X3' });
    expect(findPlatformForDevice(aristaDev, PLATFORM_REGISTRY)?.platform_id).toBe('arista');
  });

  test('maps Pica8 platforms 1:1', () => {
    const picaDev = dev('leaf', { platform: 'pica8', model: 'PicOS 48x10G' });
    expect(findPlatformForDevice(picaDev, PLATFORM_REGISTRY)?.platform_id).toBe('pica8');
  });
});
