import { Inbox } from 'lucide-react';
import { StatusDot } from '@/components/ui/StatusDot';
import { vlanColor, vlanColorMuted } from '@/lib/vlan';
import type { ThemeMode } from '@/lib/palette';
import { cn } from '@/lib/cn';
import type { ChangeRequest, Port } from '@/types';

interface PortCardProps {
  port: Port;
  selected: boolean;
  theme: ThemeMode;
  pendingRequests: ChangeRequest[];
  onClick: () => void;
}

const STATE_BG: Record<Port['state'], string> = {
  up: 'bg-bg-elev-1',
  down: 'bg-bg-elev-1/40',
  disabled: 'bg-bg-elev-1/60',
};

export function PortCard({ port, selected, theme, pendingRequests, onClick }: PortCardProps) {
  const color = vlanColor(port.untagged_vlan, theme);
  const muted = vlanColorMuted(port.untagged_vlan, theme);
  return (
    <button
      type="button"
      data-port={port.name}
      data-testid={`port-card-${port.name}`}
      onClick={onClick}
      className={cn(
        'group relative flex w-[124px] shrink-0 flex-col gap-1 rounded-lg border border-border p-2 text-left transition-all',
        STATE_BG[port.state],
        // Keep down/disabled ports visually de-emphasized but legible —
        // global `opacity-60` killed text contrast (axe-core 4.5:1).
        port.state === 'down' && 'border-dashed',
        port.state === 'disabled' && 'border-warn/30',
        selected
          ? 'border-accent ring-2 ring-accent/30 -translate-y-0.5 bg-bg-elev-2 shadow-lg'
          : 'hover:border-border-strong hover:-translate-y-px',
      )}
      style={selected ? { borderColor: color, boxShadow: `0 0 24px -4px ${muted}` } : undefined}
    >
      <header className="flex items-center justify-between">
        <span className="nb-mono text-[11px] text-fg">{port.name}</span>
        <StatusDot
          state={port.state}
          pulse={port.state === 'up' && port.traffic > 0.4}
          size={6}
        />
      </header>
      <div className="flex items-baseline gap-1.5">
        {/* Untagged VLAN is configuration, not live link state — show it even
            when the port is down (the card is already de-emphasized for down
            ports). Only "—" when there is genuinely no access VLAN. */}
        {port.untagged_vlan != null ? (
          <span className="nb-mono text-2xl font-semibold leading-none" style={{ color }}>
            {port.untagged_vlan}
          </span>
        ) : (
          <span className="nb-mono text-2xl font-semibold leading-none text-fg-subtle">—</span>
        )}
        {port.tagged_vlans.length > 0 && (
          <span
            className="rounded-sm border px-1 py-px text-[9px] font-semibold uppercase tracking-wider"
            style={{ borderColor: color, color }}
          >
            T+{port.tagged_vlans.length}
          </span>
        )}
      </div>
      <div
        className="line-clamp-2 min-h-[24px] text-[10px] text-fg-muted"
        title={port.description || undefined}
      >
        {port.description ||
          (port.state === 'down'
            ? 'no link'
            : port.state === 'disabled'
              ? 'admin disabled'
              : 'no description')}
      </div>
      {pendingRequests.length > 0 && (
        <div className="flex items-center gap-1 rounded-md bg-warn/15 px-1.5 py-0.5 text-[10px] font-semibold text-warn">
          <Inbox size={10} />
          <span>{pendingRequests.length} pending</span>
        </div>
      )}
    </button>
  );
}
