/**
 * Connector geometry — the single definition of what each cage type looks like.
 *
 * There were two copies of this: the panel-scale cage in
 * components/faceplate/PortCage and the inline glyph in shared/ConnectorIcon.
 * Same shapes, drawn twice, free to drift — change the RJ45 keyway in one and
 * the two stop agreeing about what an RJ45 is.
 *
 * So the SHAPE lives here, expressed as primitives inside a caller-supplied
 * box, and the callers own only STYLE and SCALE. A renderer decides what a
 * `mouth` is filled with; it does not decide where the keyway sits.
 *
 * Pure maths — no React, no styling, no units. The box is whatever coordinate
 * space the caller is drawing in (SVG user units at panel scale, or a 24x24
 * icon viewBox); every value is derived from it proportionally.
 */

import type { ConnectorType } from '@/lib/faceplate';

/** Box the connector is drawn inside, in the caller's coordinate space. */
export interface ShapeBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * What a part MEANS, so each renderer can style it its own way:
 *   mouth   — the opening (incl. the RJ45 latch keyway, as one silhouette)
 *   contact — a gold pin in the RJ45 contact block
 *   rib     — QSFP divider across the mouth
 *   bale    — transceiver latch bale on the left of the cage
 */
export type ConnectorPartRole = 'mouth' | 'contact' | 'rib' | 'bale';

export type ConnectorPart =
  | { kind: 'path'; role: ConnectorPartRole; d: string }
  | { kind: 'rect'; role: ConnectorPartRole; x: number; y: number; w: number; h: number }
  | { kind: 'line'; role: ConnectorPartRole; x1: number; y1: number; x2: number; y2: number };

/** Number of contacts in an RJ45 — 8P8C. */
export const RJ45_CONTACTS = 8;

/**
 * RJ45: a rectangular opening with the latch keyway hanging below centre, plus
 * the contact block. The keyway is the cue that makes an RJ45 identifiable —
 * without it the shape is a plain box and reads as any other port.
 */
function rj45Parts(box: ShapeBox): ConnectorPart[] {
  const { x, y, w, h } = box;
  const mw = w * 0.72;
  const mh = h * 0.5;
  const mx = x + (w - mw) / 2;
  const my = y + h * 0.16;
  const keyW = mw * 0.36;
  const keyH = h * 0.16;

  const parts: ConnectorPart[] = [
    {
      kind: 'path',
      role: 'mouth',
      d: [
        `M${mx} ${my}`,
        `h${mw}`,
        `v${mh}`,
        `h${-(mw - keyW) / 2}`,
        `v${keyH}`,
        `h${-keyW}`,
        `v${-keyH}`,
        `h${-(mw - keyW) / 2}`,
        'z',
      ].join(' '),
    },
  ];

  const pinW = mw * 0.055;
  const span = mw * 0.84;
  for (let i = 0; i < RJ45_CONTACTS; i++) {
    parts.push({
      kind: 'rect',
      role: 'contact',
      x: mx + mw * 0.08 + (i * span) / RJ45_CONTACTS,
      y: my + mh * 0.12,
      w: pinW,
      h: mh * 0.42,
    });
  }
  return parts;
}

/** SFP / SFP+ / SFP28 / QSFP: a letterbox mouth with a latch bale, plus a rib on QSFP. */
function transceiverParts(box: ShapeBox, connector: ConnectorType): ConnectorPart[] {
  const { x, y, w, h } = box;
  const mw = w * 0.72;
  const mh = h * (connector === 'qsfp' ? 0.52 : 0.46);
  const mx = x + (w - mw) / 2;
  const my = y + (h - mh) / 2;
  const midY = y + h / 2;

  const parts: ConnectorPart[] = [
    { kind: 'rect', role: 'mouth', x: mx, y: my, w: mw, h: mh },
    { kind: 'line', role: 'bale', x1: mx - w * 0.06, y1: midY, x2: mx, y2: midY },
  ];
  // The rib is the only thing separating a QSFP mouth from an SFP one.
  if (connector === 'qsfp') {
    parts.push({
      kind: 'line',
      role: 'rib',
      x1: mx + mw * 0.04,
      y1: midY,
      x2: mx + mw * 0.96,
      y2: midY,
    });
  }
  return parts;
}

/** Unknown media: a bare mouth, so it never impersonates a known connector. */
function unknownParts(box: ShapeBox): ConnectorPart[] {
  const { x, y, w, h } = box;
  const mw = w * 0.6;
  const mh = h * 0.34;
  return [
    { kind: 'rect', role: 'mouth', x: x + (w - mw) / 2, y: y + (h - mh) / 2, w: mw, h: mh },
  ];
}

/**
 * Parts for a connector, in draw order (back to front).
 *
 * Callers render these however they like — the panel fills the mouth with a
 * sunken tone and the icon leaves it hollow — but neither decides the geometry.
 */
export function connectorParts(connector: ConnectorType, box: ShapeBox): ConnectorPart[] {
  switch (connector) {
    case 'rj45':
      return rj45Parts(box);
    case 'sfp':
    case 'sfp28':
    case 'qsfp':
      return transceiverParts(box, connector);
    case 'unknown':
      return unknownParts(box);
  }
}
