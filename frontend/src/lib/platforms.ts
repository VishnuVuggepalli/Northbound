/**
 * Platform-registry helpers.
 *
 * The platform catalog (capabilities, display names) is REAL data served by the
 * backend `GET /api/platforms` and loaded via `usePlatforms()`. These are pure
 * lookups over that fetched list — no hardcoded/mock dataset.
 */
import type { Device, PlatformId, PlatformRegistryEntry } from '@/types';

export function findPlatform(
  id: PlatformId | string,
  platforms: readonly PlatformRegistryEntry[],
): PlatformRegistryEntry | undefined {
  return platforms.find((p) => p.platform_id === id);
}

/** Resolve the registry entry for a device from a fetched platform list. */
export function findPlatformForDevice(
  device: Pick<Device, 'platform' | 'model'>,
  platforms: readonly PlatformRegistryEntry[],
): PlatformRegistryEntry | null {
  return platforms.find((p) => p.platform === device.platform) ?? null;
}
