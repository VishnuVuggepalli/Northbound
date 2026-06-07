import { useEffect, useRef } from 'react';
import { Kbd } from '@/shared/Kbd';
import { PortCard } from './PortCard';
import type { ThemeMode } from '@/lib/palette';
import type { ChangeRequest, Device, Port } from '@/models';

interface PortStripProps {
  device: Device;
  ports: Port[];
  selected: string | null;
  requests: ChangeRequest[];
  theme: ThemeMode;
  onSelect: (name: string) => void;
}

export function PortStrip({
  device,
  ports,
  selected,
  requests,
  theme,
  onSelect,
}: PortStripProps) {
  const wrapRef = useRef<HTMLDivElement>(null);

  // Auto-scroll the selected port into view (used by `j`/`k` shortcuts).
  useEffect(() => {
    if (!selected) return;
    const el = wrapRef.current?.querySelector<HTMLElement>(
      `[data-port="${CSS.escape(selected)}"]`,
    );
    el?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  }, [selected]);

  const counts = {
    up: ports.filter((p) => p.state === 'up').length,
    down: ports.filter((p) => p.state === 'down').length,
    disabled: ports.filter((p) => p.state === 'disabled').length,
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 text-xs">
        <div className="flex items-center gap-3 text-fg-muted">
          <span className="nb-mono font-semibold text-fg">{ports.length} ports</span>
          <Legend label={`${counts.up} up`} color="bg-success" />
          <Legend label={`${counts.down} down`} color="bg-danger/70" />
          <Legend label={`${counts.disabled} disabled`} color="bg-warn" />
        </div>
        <div className="flex items-center gap-1.5 text-fg-muted">
          <Kbd>j</Kbd>
          <Kbd>k</Kbd>
          <span>to move</span>
          <span>·</span>
          <Kbd>r</Kbd>
          <span>to request</span>
        </div>
      </header>
      <div
        ref={wrapRef}
        className="nb-scroll flex-1 overflow-x-auto overflow-y-hidden border-t border-border px-4 py-3"
      >
        <div className="flex gap-2 pr-4">
          {ports.map((p) => (
            <PortCard
              key={p.name}
              port={p}
              theme={theme}
              selected={selected === p.name}
              pendingRequests={requests.filter(
                (r) =>
                  r.device_id === device.id &&
                  r.port_name === p.name &&
                  r.status === 'pending',
              )}
              onClick={() => onSelect(p.name)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function Legend({ label, color }: { label: string; color: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${color}`} />
      <span>{label}</span>
    </span>
  );
}
