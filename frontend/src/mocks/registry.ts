/**
 * Onboarding wizard — platform registry (mock / fallback dataset).
 *
 * The shape mirrors the `DriverCapabilities` from `principal-engineering.md`
 * (D5/D8 + the SwOS / LLDP / vendor-UI extensions). The real `GET
 * /api/platforms` endpoint returns the same capability object, so the wizard
 * UI doesn't change when wired to the backend — `usePlatforms()` swaps the
 * data source while this stays the offline fallback.
 *
 * Platform set matches the real backend: arista, cisco, pica8, freebsd. (MikroTik
 * RouterOS / SwOS were dropped when the backend driver set was finalized.)
 */

import type { Device, PlatformId, PlatformRegistryEntry } from '@/types';

export const PLATFORM_REGISTRY: readonly PlatformRegistryEntry[] = [
  {
    platform_id: 'arista',
    platform: 'arista',
    display_name: 'Arista EOS',
    description:
      'eAPI over HTTPS. Apply via configure session + commit timer 60 (commit-confirm).',
    defaultPort: 443,
    capabilities: {
      writable: true,
      supports_commit_confirm: true,
      native_api_available: true,
      supports_snmp_read: false,
      supports_lldp: true,
      max_concurrency: 5,
      auth_methods: ['password'],
    },
    web_ui_url_template: 'https://{mgmt_ip}/',
  },
  {
    platform_id: 'cisco',
    platform: 'cisco',
    display_name: 'Cisco IOS / NX-OS',
    description:
      'NX-API (JSON-RPC) / SSH CLI. Apply via checkpoint + config; commit-confirm window is enforced by Northbound (NX-OS has no device-armed rollback timer).',
    defaultPort: 443,
    capabilities: {
      writable: true,
      supports_commit_confirm: true,
      native_api_available: true,
      supports_snmp_read: false,
      supports_lldp: true,
      max_concurrency: 5,
      auth_methods: ['password'],
    },
    web_ui_url_template: 'https://{mgmt_ip}/',
  },
  {
    platform_id: 'pica8',
    platform: 'pica8',
    display_name: 'Pica8 PicOS',
    description:
      'NETCONF (sync, threadpool). Apply via edit-config with confirmed and confirm-timeout. SSH fallback.',
    defaultPort: 830,
    capabilities: {
      writable: true,
      supports_commit_confirm: true,
      native_api_available: true,
      supports_snmp_read: false,
      supports_lldp: true,
      max_concurrency: 4,
      auth_methods: ['password', 'ssh_key'],
    },
    web_ui_url_template: 'https://{mgmt_ip}:8888/',
  },
  {
    platform_id: 'freebsd',
    platform: 'freebsd',
    display_name: 'FreeBSD (read-only)',
    description:
      'SSH only. Read-only forever — used for routers and the VPN node. Writes are blocked at four layers.',
    defaultPort: 22,
    capabilities: {
      writable: false,
      supports_commit_confirm: false,
      native_api_available: false,
      supports_snmp_read: false,
      supports_lldp: false,
      max_concurrency: 1,
      auth_methods: ['ssh_key'],
    },
    web_ui_url_template: null,
    notes: 'No vendor web UI. Use SSH for any inspection.',
  },
];

export function findPlatform(id: PlatformId | string): PlatformRegistryEntry | undefined {
  return PLATFORM_REGISTRY.find((p) => p.platform_id === id);
}

/**
 * Resolve the registry entry for a device. Driver IDs map 1:1 onto the broad
 * `Platform` category for the current backend, so this is a straight lookup.
 */
export function findPlatformForDevice(
  device: Pick<Device, 'platform' | 'model'>,
  platforms: readonly PlatformRegistryEntry[] = PLATFORM_REGISTRY,
): PlatformRegistryEntry | null {
  return platforms.find((p) => p.platform === device.platform) ?? null;
}
