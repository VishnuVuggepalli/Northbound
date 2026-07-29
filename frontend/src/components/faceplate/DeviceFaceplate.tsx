/**
 * Device faceplate — a 2D SVG panel drawn from the ports the device reports.
 *
 * Replaces the WebGL chassis as the primary port surface. A faceplate is
 * something an operator READS: which port, what VLAN, is it up, is a change
 * pending. Flat vector serves that better than a lit 3D box — it stays crisp at
 * any zoom, prints and screenshots cleanly, has no depth buffer to fight and no
 * material to shimmer, and costs no GPU context.
 *
 * Layout comes from lib/faceplate (groups, rows, numbering) via ./geometry
 * (absolute coordinates). This component only draws.
 */

import { useMemo } from 'react';
import { deriveFaceplate, CONNECTOR_LABEL } from '@/lib/faceplate';
import { vlanColor } from '@/lib/vlan';
import { layoutFaceplate, LABEL_H } from './geometry';
import { PortCage } from './PortCage';
import type { ThemeMode } from '@/lib/palette';
import type { ChangeRequest, Device, Port } from '@/models';
import { cn } from '@/lib/cn';

export interface DeviceFaceplateProps {
  device: Device;
  ports: Port[];
  requests: ChangeRequest[];
  selectedPort: string | null;
  theme: ThemeMode;
  onSelect: (portName: string) => void;
  className?: string;
}

export function DeviceFaceplate({
  device,
  ports,
  requests,
  selectedPort,
  theme,
  onSelect,
  className,
}: DeviceFaceplateProps) {
  const faceplate = useMemo(() => deriveFaceplate(ports, device.portKind), [ports, device.portKind]);
  const geo = useMemo(() => layoutFaceplate(faceplate), [faceplate]);

  // Ports with an open request, so the panel shows what is ABOUT to change and
  // not only current state.
  const pendingPorts = useMemo(() => {
    const set = new Set<string>();
    for (const r of requests) {
      if (r.device_id === device.id && r.status === 'pending' && r.port_name) set.add(r.port_name);
    }
    return set;
  }, [requests, device.id]);

  const provisional = faceplate.source === 'platform-fallback';

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      {provisional && (
        // A guess must never be presented as fact.
        <p className="text-[11px] text-warn">
          Port list unavailable — showing the generic {device.platform} layout, not this device.
        </p>
      )}

      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${geo.width} ${geo.height}`}
          className={cn('h-auto w-full min-w-[640px]', provisional && 'opacity-60')}
          role="group"
          aria-label={`${device.name} front panel, ${faceplate.portCount} ports`}
          preserveAspectRatio="xMidYMid meet"
        >
          {/* Chassis */}
          <rect
            x={0.5}
            y={0.5}
            width={geo.chassis.w - 1}
            height={geo.chassis.h - 1}
            rx={4}
            className="fill-bg-elev-1 stroke-border-strong"
            strokeWidth={1}
          />
          {/* Vendor colour strip */}
          <rect
            x={geo.brand.x}
            y={geo.brand.y}
            width={geo.brand.w}
            height={geo.brand.h}
            rx={2}
            /* NOTE: `fill-accent/25` does NOT work — `accent` is a raw
               `var(--nb-accent)`, and Tailwind's opacity modifier cannot inject
               an alpha into it for `fill`. The invalid value falls back to
               SVG's default black, which rendered the vendor strip as a black
               slab in light theme. Set fill + fillOpacity explicitly; the var
               still tracks the theme. */
            fill="var(--nb-accent)"
            fillOpacity={0.2}
            stroke="var(--nb-accent)"
            strokeOpacity={0.45}
            strokeWidth={0.8}
          />
          <text
            x={geo.brand.x + geo.brand.w / 2}
            y={geo.brand.y + geo.brand.h / 2}
            textAnchor="middle"
            dominantBaseline="middle"
            transform={`rotate(-90 ${geo.brand.x + geo.brand.w / 2} ${geo.brand.y + geo.brand.h / 2})`}
            className="fill-fg-muted"
            style={{ fontSize: 8, letterSpacing: 1, textTransform: 'uppercase' }}
          >
            {device.platform}
          </text>

          {/* Per-bank caption: media type and cage count */}
          {geo.groups.map((g) => (
            <text
              key={`${g.prefix}-label`}
              x={g.x}
              y={g.y + g.h + LABEL_H - 3}
              className="fill-fg-subtle"
              style={{ fontSize: 7, letterSpacing: 0.4 }}
            >
              {CONNECTOR_LABEL[g.connector]} ·{' '}
              {geo.cages.filter((c) => c.connector === g.connector && c.x >= g.x && c.x < g.x + g.w).length}
            </text>
          ))}

          {/* Cages */}
          {geo.cages.map((cage) => (
            <PortCage
              key={cage.id}
              cage={cage}
              selected={cage.ports.some((p) => p.name === selectedPort)}
              pending={cage.ports.some((p) => pendingPorts.has(p.name))}
              vlanColor={vlanColor(cage.ports[0]?.untagged_vlan ?? 0, theme)}
              onSelect={onSelect}
            />
          ))}
        </svg>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-fg-muted">
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-ok" /> Link up
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-warn" /> Admin disabled
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-fg-subtle" /> Down
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" /> Pending change
        </span>
        <span className="ml-auto nb-mono">
          {faceplate.slotCount} cages · {faceplate.portCount} ports
        </span>
      </div>
    </div>
  );
}
