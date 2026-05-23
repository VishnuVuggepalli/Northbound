/**
 * VendorActions — vendor-UI escape hatch for the device / port surfaces.
 *
 * Two modes, picked by the registry entry's `web_ui_url_template`:
 *
 *   - String template: render an "Open in vendor UI ↗" button (anchor under
 *     the hood so middle-click and cmd-click work). Tooltip explains why.
 *   - `null` (FreeBSD): render an SSH copy-chip with the username + mgmt_ip.
 *
 * Northbound is deliberately scoped (PM hard NO list); when something falls
 * outside, the user should escape cleanly rather than hit a dead end.
 */

import { Copy, ExternalLink, Terminal } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { vendorWebUiUrl } from '@/lib/devicePolicy';
import { pushToast } from '@/store/toast';
import type { Device, PlatformRegistryEntry } from '@/types';

interface VendorActionsProps {
  device: Device;
  platform: PlatformRegistryEntry | null | undefined;
  /** Optional compact variant for the port panel where space is tight. */
  size?: 'sm' | 'md';
  className?: string;
}

export function VendorActions({ device, platform, size = 'sm', className }: VendorActionsProps) {
  if (!platform) return null;

  const webUrl = vendorWebUiUrl(device, platform);
  if (webUrl) {
    return (
      <Button
        kind="ghost"
        size={size}
        href={webUrl}
        target="_blank"
        rel="noopener noreferrer"
        leftIcon={<ExternalLink size={12} aria-hidden />}
        title="Northbound is scoped — use the vendor UI for advanced changes"
        aria-label={`Open ${platform.display_name} web UI for ${device.name} in a new tab`}
        data-testid="vendor-ui-link"
        className={className}
      >
        Open in vendor UI
      </Button>
    );
  }

  // No web UI → show an SSH copy-chip (FreeBSD).
  const user = device.ssh_user || 'root';
  const cmd = `ssh ${user}@${device.mgmt_ip}`;
  return (
    <button
      type="button"
      onClick={() => {
        void writeToClipboard(cmd);
      }}
      title="Copy SSH command"
      aria-label={`Copy SSH command for ${device.name}`}
      data-testid="ssh-copy-chip"
      className={
        'inline-flex h-7 items-center gap-1.5 rounded-md border border-border bg-bg-elev-1 px-2 text-xs text-fg hover:border-border-strong hover:bg-bg-elev-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ' +
        (className ?? '')
      }
    >
      <Terminal size={12} aria-hidden className="text-fg-muted" />
      <span className="nb-mono">{cmd}</span>
      <Copy size={11} aria-hidden className="text-fg-subtle" />
    </button>
  );
}

async function writeToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    pushToast({
      kind: 'success',
      title: 'Copied',
      message: text,
    });
  } catch (err) {
    pushToast({
      kind: 'error',
      title: 'Copy failed',
      message: err instanceof Error ? err.message : 'Clipboard unavailable',
    });
  }
}
