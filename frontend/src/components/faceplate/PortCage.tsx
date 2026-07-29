/**
 * One port cage on the SVG faceplate.
 *
 * Draws the connector at panel scale — an RJ45 keyway and contact block, or a
 * transceiver cage mouth with its latch bale — plus the live state an operator
 * reads at a glance: link LED, VLAN identity stripe, breakout marker, pending
 * change, selection.
 *
 * Everything is flat 2D. There is no lighting, no material and no depth buffer,
 * so nothing can shimmer or z-fight the way the WebGL faceplate did, and it
 * stays crisp at any zoom.
 */

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

export function PortCage({ cage, selected, pending, vlanColor, onSelect }: PortCageProps) {
  const primary = cage.ports[0];
  const brokenOut = cage.ports.length > 1;
  const { x, y, w, h } = cage;

  // Inner mouth, inset from the cage shell.
  const mx = x + w * 0.14;
  const my = y + h * 0.16;
  const mw = w * 0.72;
  const mh = h * (cage.connector === 'rj45' ? 0.5 : 0.46);

  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={`Port ${cage.id}${primary ? `, ${primary.state}` : ''}`}
      aria-pressed={selected}
      className="cursor-pointer outline-none [&:focus-visible>.cage-shell]:stroke-accent"
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

      {cage.connector === 'rj45' ? (
        <>
          {/* Mouth + latch keyway as one silhouette — the keyway is what makes
              an RJ45 identifiable rather than a generic rectangle. */}
          <path
            d={[
              `M${mx} ${my}`,
              `h${mw}`,
              `v${mh}`,
              `h${-mw * 0.32}`,
              `v${h * 0.16}`,
              `h${-mw * 0.36}`,
              `v${-h * 0.16}`,
              `h${-mw * 0.32}`,
              'z',
            ].join(' ')}
            className="fill-bg-sunken stroke-border"
            strokeWidth={0.6}
          />
          {/* Contact block */}
          {Array.from({ length: 8 }, (_, i) => (
            <rect
              key={i}
              x={mx + mw * 0.08 + (i * mw * 0.84) / 8}
              y={my + mh * 0.12}
              width={mw * 0.055}
              height={mh * 0.42}
              fill="var(--nb-warn)"
              fillOpacity={0.7}
            />
          ))}
        </>
      ) : (
        <>
          {/* Transceiver cage mouth */}
          <rect
            x={mx}
            y={y + (h - mh) / 2}
            width={mw}
            height={mh}
            rx={1}
            className="fill-bg-sunken stroke-border"
            strokeWidth={0.6}
          />
          {/* Latch bale on the left, as on a real cage */}
          <line
            x1={mx - w * 0.06}
            y1={y + h / 2}
            x2={mx}
            y2={y + h / 2}
            className="stroke-fg-subtle"
            strokeWidth={1}
            strokeLinecap="round"
          />
          {/* QSFP carries a divider rib; SFP does not */}
          {cage.connector === 'qsfp' && (
            <line
              x1={mx + 1}
              y1={y + h / 2}
              x2={mx + mw - 1}
              y2={y + h / 2}
              className="stroke-border"
              strokeWidth={0.6}
            />
          )}
        </>
      )}

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
        <circle cx={x + w - 4} cy={y + h - 6} r={2} className="fill-accent stroke-bg" strokeWidth={0.8} />
      )}
    </g>
  );
}
