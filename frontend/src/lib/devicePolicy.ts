/**
 * Device write-policy + vendor-UI helpers.
 *
 * Hoisted (F21b) so PortPanel, RequestRow, DeviceDetailPage and any future
 * caller share a single source of truth. The previous inline copies disagreed
 * subtly — RequestRow only checked `device.role`, PortPanel didn't check at
 * all. With SwOS landing read-only via driver capability (not role), the
 * unified rule is:
 *
 *   "Write-locked when the role is fundamentally read-only (router / vpn)
 *    OR when the platform driver itself can't write."
 *
 * Co-located here so the rule is testable in isolation (vitest unit) without
 * dragging in TanStack Query or React.
 */

import { findPlatformForDevice } from '@/lib/platforms';
import type { Device, PlatformRegistryEntry } from '@/models';

/**
 * Returns true when no admin write should be possible against this device,
 * regardless of UI role. Four layers of defense:
 *
 *   1. Role-based (router / vpn) — these run FreeBSD and are never writable
 *   2. Driver capability (`platform.capabilities.writable === false`) — SwOS,
 *      FreeBSD; explicit in the registry, can't be flipped from the UI
 *   3. (Backend) API rejects write to a writable=false driver
 *   4. (Backend) DB CHECK constraint blocks `device_role IN ('router','vpn')`
 *
 * The first two are enforced here; the last two ship server-side.
 */
export function isWriteLocked(
  device: Pick<Device, 'role'>,
  platform: PlatformRegistryEntry | null | undefined,
): boolean {
  if (device.role === 'router' || device.role === 'vpn') return true;
  if (platform && platform.capabilities.writable === false) return true;
  return false;
}

/**
 * Render the vendor's own web UI URL for this device. Returns `null` when the
 * platform doesn't ship a web UI (FreeBSD) — callers should render an SSH
 * copy-chip instead.
 */
export function vendorWebUiUrl(
  device: Pick<Device, 'mgmt_ip'>,
  platform: PlatformRegistryEntry | null | undefined,
): string | null {
  if (!platform || !platform.web_ui_url_template) return null;
  return platform.web_ui_url_template.replace('{mgmt_ip}', device.mgmt_ip);
}

// Re-export so callers can import a single module instead of two.
export { findPlatformForDevice };
