/**
 * Onboarding wizard — platform registry.
 *
 * The shape mirrors the `DriverCapabilities` from `principal-engineering.md`
 * (D5/D8). The future `GET /api/platforms` endpoint returns the same object
 * unchanged, so the wizard UI doesn't need to change when we wire it to the
 * real backend.
 */

import type { PlatformRegistryEntry } from '@/types';

export const PLATFORM_REGISTRY: readonly PlatformRegistryEntry[] = [
  {
    platform: 'mikrotik',
    label: 'MikroTik RouterOS',
    description:
      'RouterOS 7.x. REST API preferred (writes via PATCH); SSH fallback. Backup-then-apply with safe-mode.',
    defaultPort: 443,
    capabilities: {
      writable: true,
      supports_commit_confirm: false,
      native_api_available: true,
      max_concurrency: 5,
      auth_kinds: ['password', 'api_token'],
    },
  },
  {
    platform: 'arista',
    label: 'Arista EOS',
    description:
      'eAPI over HTTPS. Apply via configure session + commit timer 60 (commit-confirm).',
    defaultPort: 443,
    capabilities: {
      writable: true,
      supports_commit_confirm: true,
      native_api_available: true,
      max_concurrency: 5,
      auth_kinds: ['password', 'api_token'],
    },
  },
  {
    platform: 'pica8',
    label: 'Pica8 PicOS',
    description:
      'NETCONF (sync, threadpool). Apply via edit-config with confirmed and confirm-timeout. SSH fallback.',
    defaultPort: 830,
    capabilities: {
      writable: true,
      supports_commit_confirm: true,
      native_api_available: true,
      max_concurrency: 4,
      auth_kinds: ['password', 'ssh_key'],
    },
  },
  {
    platform: 'freebsd',
    label: 'FreeBSD (read-only)',
    description:
      'SSH only. Read-only forever — used for routers and the VPN node. Writes are blocked at four layers.',
    defaultPort: 22,
    capabilities: {
      writable: false,
      supports_commit_confirm: false,
      native_api_available: false,
      max_concurrency: 1,
      auth_kinds: ['password', 'ssh_key'],
    },
  },
];

export function findPlatform(id: string): PlatformRegistryEntry | undefined {
  return PLATFORM_REGISTRY.find((p) => p.platform === id);
}
