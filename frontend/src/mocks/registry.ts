/**
 * Onboarding wizard — platform registry.
 *
 * The shape mirrors the `DriverCapabilities` from `principal-engineering.md`
 * (D5/D8 + the SwOS / LLDP / vendor-UI extensions). The future `GET
 * /api/platforms` endpoint returns the same object unchanged, so the wizard
 * UI doesn't need to change when we wire it to the real backend.
 */

import type { Device, PlatformId, PlatformRegistryEntry } from '@/types';

export const PLATFORM_REGISTRY: readonly PlatformRegistryEntry[] = [
  {
    platform_id: 'mikrotik_routeros',
    platform: 'mikrotik',
    display_name: 'MikroTik RouterOS',
    description:
      'RouterOS 7.x. REST API preferred (writes via PATCH); SSH fallback. Backup-then-apply with safe-mode.',
    defaultPort: 443,
    capabilities: {
      writable: true,
      supports_commit_confirm: false,
      native_api_available: true,
      supports_snmp_read: true,
      supports_lldp: true,
      max_concurrency: 5,
      auth_methods: ['password', 'api_token'],
    },
    web_ui_url_template: 'http://{mgmt_ip}/webfig/',
  },
  {
    platform_id: 'mikrotik_swos',
    platform: 'mikrotik',
    display_name: 'MikroTik SwOS',
    description:
      'Read-only via SNMP (LLDP, port stats, VLANs) with HTTP scrape for opaque backups. Writes are blocked at the driver layer.',
    defaultPort: 161,
    capabilities: {
      writable: false,
      supports_commit_confirm: false,
      native_api_available: false,
      supports_snmp_read: true,
      supports_lldp: true,
      max_concurrency: 1,
      auth_methods: ['password', 'snmp_v2c_community'],
    },
    web_ui_url_template: 'http://{mgmt_ip}/',
    notes: 'Read-only. Use the SwOS web UI for changes.',
  },
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
      supports_snmp_read: true,
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
      supports_snmp_read: true,
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
 * Disambiguate registry entry for a device. RouterOS and SwOS both share
 * `device.platform === 'mikrotik'`, so we inspect `device.model` for an
 * explicit `/swos/i` marker. All other platforms map 1:1.
 */
export function findPlatformForDevice(
  device: Pick<Device, 'platform' | 'model'>,
  platforms: readonly PlatformRegistryEntry[] = PLATFORM_REGISTRY,
): PlatformRegistryEntry | null {
  if (device.platform === 'mikrotik') {
    const isSwOS = /swos/i.test(device.model);
    const targetId: PlatformId = isSwOS ? 'mikrotik_swos' : 'mikrotik_routeros';
    return platforms.find((p) => p.platform_id === targetId) ?? null;
  }
  return platforms.find((p) => p.platform === device.platform) ?? null;
}
