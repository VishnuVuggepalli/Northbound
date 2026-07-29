/**
 * One port cage on the SVG faceplate.
 *
 * Geometry is NOT defined here. It comes from lib/connectorShape, the single
 * owner of what each connector looks like; this file owns only panel-scale
 * STYLING plus the live state an operator reads at a glance — link LED, VLAN
 * identity stripe, breakout marker, pending change, selection. The inline glyph
 * (shared/ConnectorIcon) draws the same parts, lighter.
 *
 * Everything is flat 2D. No lighting, no material, no depth buffer — so nothing
 * can shimmer or z-fight the way the WebGL faceplate did, and it stays crisp at
 * any zoom.
 */

import { connectorParts, type ConnectorPart } from '@/lib/connectorShape';
import type { CageBox } from './geometry';
import type { Port } from '@/models';

export interface PortCageProps {
  cage: CageBox;
  selected: boolean;
  /** Ports with an open change request — drawn with a pending marker. */
  pending: boolean;
  /** VLAN identity colour for the cage's primary port. */
  vlanColor: string;
  onSelect: (portName: string) => void;
}

/** Link state drives the LED. Mirrors the legend under the faceplate. */
function ledClass(port: Port | undefined): string {
  if (!port) return 'fill-fg-subtle';
  if (port.state === 'up') return 'fill-ok';
  if (port.state === 'disabled') return 'fill-warn';
  return 'fill-fg-subtle';
}

/**
 * Style one part at panel scale — filled mouths, gold contacts.
 *
 * NOTE the contacts use an explicit fill + fillOpacity rather than
 * `fill-warn/70`. `warn` is a raw `var(--nb-warn)` and Tailwind's opacity
 * modifier cannot inject an alpha into it for `fill`; the invalid value falls
 * back to SVG black. That trap has already bitten this file and the vendor
 * strip — do not reintroduce it.
 */
function renderPart(part: ConnectorPart, i: number) {
  switch (part.kind) {
    case 'path':
      return (
        <path key={i} d={part.d} className="fill-bg-sunken stroke-border" strokeWidth={0.6} />
      );
    case 'rect':
      return part.role === 'contact' ? (
        <rect
          key={i}
          x={part.x}
          y={part.y}
          width={part.w}
          height={part.h}
          fill="var(--nb-warn)"
          fillOpacity={0.7}
        />
      ) : (
        <rect
          key={i}
          x={part.x}
          y={part.y}
          width={part.w}
          height={part.h}
          rx={1}
          className="fill-bg-sunken stroke-border"
          strokeWidth={0.6}
        />
      );
    case 'line':
      return (
        <line
          key={i}
          x1={part.x1}
          y1={part.y1}
          x2={part.x2}
          y2={part.y2}
          className={part.role === 'bale' ? 'stroke-fg-subtle' : 'stroke-border'}
          strokeWidth={part.role === 'bale' ? 1 : 0.6}
          strokeLinecap="round"
        />
      );
  }
}

export function PortCage({ cage, selected, pending, vlanColor, onSelect }: PortCageProps) {
  const primary = cage.ports[0];
  const brokenOut = cage.ports.length > 1;
  const { x, y, w, h } = cage;

  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={`Port ${cage.id}${primary ? `, ${primary.state}` : ''}`}
      aria-pressed={selected}
      className="group cursor-pointer outline-none [&:focus-visible>.cage-shell]:stroke-accent"
      onClick={() => primary && onSelect(primary.name)}
      onKeyDown={(e) => {
        if ((e.key === 'Enter' || e.key === ' ') && primary) {
          e.preventDefault();
          onSelect(primary.name);
        }
      }}
    >
      {/* Selection halo, behind the shell */}
      {selected && (
        <rect
          x={x - 2.5}
          y={y - 2.5}
          width={w + 5}
          height={h + 5}
          rx={3}
          fill="none"
          stroke={vlanColor}
          strokeWidth={2}
        />
      )}

      {/* Cage shell */}
      <rect
        className="cage-shell fill-bg-elev-2 stroke-border-strong transition-colors group-hover:stroke-fg-muted"
        x={x}
        y={y}
        width={w}
        height={h}
        rx={2}
        strokeWidth={1}
      />

      {/* Connector geometry — shared with the inline glyph. */}
      {connectorParts(cage.connector, cage).map(renderPart)}

      {/* VLAN identity stripe along the bottom edge */}
      {primary && primary.state !== 'down' && (
        <rect x={x + 2} y={y + h - 3.2} width={w - 4} height={2} rx={1} fill={vlanColor} />
      )}

      {/* Link LED */}
      <circle cx={x + 4} cy={y + 4} r={1.7} className={ledClass(primary)} />

      {/* Breakout marker — this cage carries several logical ports */}
      {brokenOut && (
        <text
          x={x + w - 3}
          y={y + 6}
          textAnchor="end"
          className="fill-fg-muted"
          style={{ fontSize: 6, fontWeight: 600 }}
        >
          ×{cage.ports.length}
        </text>
      )}

      {/* Pending change marker */}
      {pending && (
        <circle
          cx={x + w - 4}
          cy={y + h - 6}
          r={2}
          className="fill-accent stroke-bg"
          strokeWidth={0.8}
        />
      )}
    </g>
  );
}
