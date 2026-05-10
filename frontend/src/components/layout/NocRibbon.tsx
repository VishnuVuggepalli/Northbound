import { useEffect, useMemo, useState } from 'react';
import type { ChangeRequest, Device, PortMap } from '@/types';

interface NocRibbonProps {
  env: string;
  devices: Device[];
  ports: PortMap;
  requests: ChangeRequest[];
}

/**
 * The NOC ribbon — a one-line live summary of environment health. Modeled
 * after the NOC dashboards Avery already lives in.
 */
export function NocRibbon({ env, devices, ports, requests }: NocRibbonProps) {
  const stats = useMemo(() => {
    let up = 0, down = 0, dis = 0, total = 0;
    for (const d of devices) {
      const arr = ports[d.id] ?? [];
      for (const p of arr) {
        total++;
        if (p.state === 'up') up++;
        else if (p.state === 'disabled') dis++;
        else down++;
      }
    }
    const pending = requests.filter(
      (r) => r.status === 'pending' && devices.some((d) => d.id === r.device_id),
    ).length;
    return { up, down, dis, total, pending };
  }, [devices, ports, requests]);

  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const hh = String(now.getUTCHours()).padStart(2, '0');
  const mm = String(now.getUTCMinutes()).padStart(2, '0');
  const ss = String(now.getUTCSeconds()).padStart(2, '0');

  return (
    <div className="nb-mono flex items-center gap-3 border-y border-border bg-bg-elev-1/60 px-4 py-1.5 text-[11px] tracking-wide text-fg-muted">
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-success animate-pulse-soft" />
        <span className="font-semibold text-fg">{env.toUpperCase()}</span>
      </span>
      <Cell label="dev" value={devices.length} />
      <Cell label="ports" value={stats.total} />
      <Cell label="up" value={`↑${stats.up}`} tone="success" />
      <Cell label="down" value={`↓${stats.down}`} tone="danger" />
      <Cell label="dis" value={`◌${stats.dis}`} tone="warn" />
      {stats.pending > 0 && <Cell label="pending" value={stats.pending} tone="warn" />}
      <span className="ml-auto flex items-center gap-1.5">
        <span className="text-fg-subtle">utc</span>
        <span className="font-semibold text-fg">{hh}:{mm}:{ss}</span>
      </span>
    </div>
  );
}

interface CellProps {
  label: string;
  value: string | number;
  tone?: 'success' | 'warn' | 'danger';
}

const TONE: Record<NonNullable<CellProps['tone']>, string> = {
  success: 'text-success',
  warn: 'text-warn',
  danger: 'text-danger',
};

function Cell({ label, value, tone }: CellProps) {
  return (
    <span className="flex items-center gap-1">
      <span className="text-fg-subtle">{label}</span>
      <span className={tone ? TONE[tone] : 'text-fg'}>{value}</span>
    </span>
  );
}
