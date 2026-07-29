/**
 * 2D connector faces — RJ45, SFP/SFP+, QSFP.
 *
 * Why hand-authored rather than an icon pack: the free packs (SVG Repo, Noun
 * Project, Flaticon, UXWing) ship a single decorative "ethernet port" glyph.
 * None covers RJ45 + SFP + QSFP as one coherent set, and none is drawn to be
 * repeated 32 times at 16px while carrying link state. These are simple
 * geometry — a keyway and eight contacts, or a letterbox mouth behind a shield
 * lip — so drawing them keeps the repo free of third-party asset licensing and
 * matches the house convention (inline JSX + lucide, zero .svg files).
 *
 * Colour comes from `currentColor` and design tokens only, so these inherit
 * light/dark from whatever renders them. The 3D faceplate models the same cues
 * (see components/three/Switch3D).
 */

import type { SVGProps } from 'react';
import { cn } from '@/lib/cn';
import type { ConnectorType } from '@/lib/faceplate';

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
 * RJ45 — a rectangular opening with the latch keyway hanging below centre and
 * eight contacts along the top. The keyway is the cue that identifies an RJ45
 * at a glance; without it the shape is just a box.
 */
function Rj45Face() {
  return (
    <>
      <rect x="3.5" y="2.5" width="17" height="19" rx="1.5" className="fill-none" strokeWidth="1.4" />
      {/* Opening + keyway as one silhouette */}
      <path
        d="M6 5h12v9.5h-2.75V18h-6.5v-3.5H6z"
        strokeWidth="1.2"
        strokeLinejoin="round"
        className="fill-none"
      />
      {/* Eight contacts */}
      {Array.from({ length: 8 }, (_, i) => (
        <line
          key={i}
          x1={7.2 + i * 1.37}
          y1="5.8"
          x2={7.2 + i * 1.37}
          y2="9.4"
          strokeWidth="0.9"
          strokeLinecap="round"
          opacity="0.75"
        />
      ))}
    </>
  );
}

/** SFP / SFP+ / SFP28 — letterbox cage mouth behind a shield lip. */
function SfpFace() {
  return (
    <>
      <rect x="1.5" y="5.5" width="21" height="13" rx="1.5" className="fill-none" strokeWidth="1.4" />
      <rect x="4" y="8" width="16" height="8" rx="0.8" className="fill-none" strokeWidth="1.2" />
      {/* Latch bale on the left, as on a real transceiver cage */}
      <line x1="4" y1="12" x2="1.5" y2="12" strokeWidth="1.2" strokeLinecap="round" opacity="0.8" />
    </>
  );
}

/** QSFP — taller mouth than SFP, with the divider rib across it. */
function QsfpFace() {
  return (
    <>
      <rect x="1.5" y="4" width="21" height="16" rx="1.5" className="fill-none" strokeWidth="1.4" />
      <rect x="4" y="6.5" width="16" height="11" rx="0.8" className="fill-none" strokeWidth="1.2" />
      {/* Divider rib — the visual difference from a plain SFP mouth */}
      <line x1="4" y1="12" x2="20" y2="12" strokeWidth="1" opacity="0.7" />
      <line x1="4" y1="12" x2="1.5" y2="12" strokeWidth="1.2" strokeLinecap="round" opacity="0.8" />
    </>
  );
}

/** Unknown media — a plain cage, so it never masquerades as a known type. */
function UnknownFace() {
  return (
    <>
      <rect x="3" y="5" width="18" height="14" rx="1.5" className="fill-none" strokeWidth="1.4" />
      <line x1="9" y1="12" x2="15" y2="12" strokeWidth="1.2" strokeLinecap="round" opacity="0.6" />
    </>
  );
}

const FACE: Record<ConnectorType, () => JSX.Element> = {
  rj45: Rj45Face,
  sfp: SfpFace,
  sfp28: SfpFace,
  qsfp: QsfpFace,
  unknown: UnknownFace,
};

export function ConnectorIcon({ kind, size = 16, title, className, ...rest }: ConnectorIconProps) {
  const Face = FACE[kind] ?? UnknownFace;
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
      <Face />
    </svg>
  );
}
