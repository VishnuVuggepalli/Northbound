/**
 * Inline connector glyph — RJ45, SFP/SFP+/SFP28, QSFP.
 *
 * Geometry is NOT defined here. It comes from lib/connectorShape, the single
 * owner of what each connector looks like; this file owns only how those parts
 * are STYLED at glyph scale. The panel-scale renderer
 * (components/faceplate/PortCage) draws the same parts with heavier styling.
 * To change what an RJ45 looks like, change connectorShape — once.
 *
 * On drawing rather than sourcing: the free packs (SVG Repo — CC0, UXWing,
 * Noun Project, Flaticon) ship a single decorative "ethernet port" glyph. None
 * covers RJ45 + SFP + QSFP as a set, and none is drawn to repeat 32 times at
 * 13px while carrying link state. Drawing them also keeps the repo free of
 * third-party asset licensing and matches the house convention (inline JSX +
 * lucide, zero .svg files).
 *
 * Colour is `currentColor` only, so the glyph inherits light/dark from whatever
 * renders it.
 */

import type { SVGProps } from 'react';
import { cn } from '@/lib/cn';
import type { ConnectorType } from '@/lib/faceplate';
import { connectorParts, type ConnectorPart, type ShapeBox } from '@/lib/connectorShape';

export interface ConnectorIconProps extends Omit<SVGProps<SVGSVGElement>, 'children'> {
  kind: ConnectorType;
  size?: number;
  /**
   * Accessible label. Omit for decorative use next to a visible port name —
   * the icon is then hidden from assistive tech rather than read as noise.
   */
  title?: string;
}

/**
 * Outer cage footprint per type, in the 24x24 viewBox. Proportions follow the
 * hardware: RJ45 is near-square and tall, transceivers are letterboxes.
 */
const SHELL: Record<ConnectorType, ShapeBox> = {
  rj45: { x: 3.5, y: 2.5, w: 17, h: 19 },
  sfp: { x: 1.5, y: 5.5, w: 21, h: 13 },
  sfp28: { x: 1.5, y: 5.5, w: 21, h: 13 },
  qsfp: { x: 1.5, y: 4, w: 21, h: 16 },
  unknown: { x: 3, y: 5, w: 18, h: 14 },
};

/** Style one part at glyph scale — hollow outlines, thin strokes. */
function renderPart(part: ConnectorPart, i: number) {
  switch (part.kind) {
    case 'path':
      return <path key={i} d={part.d} fill="none" strokeWidth={1.2} strokeLinejoin="round" />;
    case 'rect':
      // Contacts are solid at this size; a hollow sub-pixel box is just mud.
      return part.role === 'contact' ? (
        <rect
          key={i}
          x={part.x}
          y={part.y}
          width={part.w}
          height={part.h}
          fill="currentColor"
          stroke="none"
          opacity={0.75}
        />
      ) : (
        <rect
          key={i}
          x={part.x}
          y={part.y}
          width={part.w}
          height={part.h}
          rx={0.8}
          fill="none"
          strokeWidth={1.2}
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
          strokeWidth={part.role === 'bale' ? 1.2 : 1}
          strokeLinecap="round"
          opacity={part.role === 'rib' ? 0.7 : 0.85}
        />
      );
  }
}

export function ConnectorIcon({ kind, size = 16, title, className, ...rest }: ConnectorIconProps) {
  const shell = SHELL[kind] ?? SHELL.unknown;
  const labelled = title !== undefined;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      className={cn('shrink-0', className)}
      role={labelled ? 'img' : undefined}
      aria-label={labelled ? title : undefined}
      aria-hidden={labelled ? undefined : true}
      focusable="false"
      {...rest}
    >
      {/* Cage shell */}
      <rect
        x={shell.x}
        y={shell.y}
        width={shell.w}
        height={shell.h}
        rx={1.5}
        fill="none"
        strokeWidth={1.4}
      />
      {connectorParts(kind, shell).map(renderPart)}
    </svg>
  );
}
