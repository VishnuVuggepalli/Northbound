/**
 * Faceplate geometry — pure layout maths, no React.
 *
 * Turns the logical faceplate (lib/faceplate: groups of cages) into absolute
 * SVG coordinates. Kept separate from the renderer so the arithmetic that
 * decides where a port sits is unit-testable without mounting anything.
 *
 * Units are SVG user units, and the component scales the whole drawing via
 * viewBox — so these are proportions, not pixels. Values follow real 1U panel
 * proportions: cages are wider than tall, stacked two high, in banks separated
 * by a wider gutter than the intra-bank pitch.
 */

import type { ConnectorType, Faceplate } from '@/lib/faceplate';
import type { Port } from '@/models';

/** Cage dimensions per connector type, in SVG units. */
const CAGE: Record<ConnectorType, { w: number; h: number }> = {
  rj45: { w: 30, h: 26 }, // near-square, the tallest cage
  sfp: { w: 30, h: 15 }, // letterbox
  sfp28: { w: 30, h: 15 },
  qsfp: { w: 34, h: 18 }, // wider and taller than SFP
  unknown: { w: 30, h: 20 },
};

export const GAP_X = 4; // between cages in a row
export const GAP_Y = 5; // between the two rows
export const GROUP_GAP = 20; // between port groups (access bank vs uplinks)
export const PAD_X = 16; // chassis inner padding
export const PAD_Y = 16;
export const BRAND_W = 26; // vendor colour strip on the left
export const LABEL_H = 11; // room under each bank for its numbering

/** One drawn cage, with the ports it carries (>1 when broken out). */
export interface CageBox {
  x: number;
  y: number;
  w: number;
  h: number;
  /** Physical cage id — port name minus any breakout lane suffix. */
  id: string;
  /** 1-based position within its group, from the port name. */
  index: number;
  ports: Port[];
  connector: ConnectorType;
  groupIndex: number;
}

export interface GroupBox {
  x: number;
  y: number;
  w: number;
  h: number;
  prefix: string;
  connector: ConnectorType;
}

export interface FaceplateGeometry {
  width: number;
  height: number;
  chassis: { x: number; y: number; w: number; h: number };
  brand: { x: number; y: number; w: number; h: number };
  groups: GroupBox[];
  cages: CageBox[];
}

/**
 * Lay the faceplate out left to right.
 *
 * Groups keep the order the faceplate produced, so uplinks named later (SFP1,
 * SFP2) sit to the right of the access bank — as on the physical panel. Within
 * a group, cages are placed at the row/col the faceplate already computed
 * (numbered down-then-right, odd on top), so the numbering convention has one
 * owner and is not re-derived here.
 */
export function layoutFaceplate(faceplate: Faceplate): FaceplateGeometry {
  const groups: GroupBox[] = [];
  const cages: CageBox[] = [];

  let cursorX = PAD_X + BRAND_W + GROUP_GAP;
  let maxGroupH = 0;

  faceplate.groups.forEach((group, groupIndex) => {
    const cage = CAGE[group.connector] ?? CAGE.unknown;
    const groupW = group.cols * cage.w + Math.max(0, group.cols - 1) * GAP_X;
    const groupH = group.rows * cage.h + Math.max(0, group.rows - 1) * GAP_Y;
    maxGroupH = Math.max(maxGroupH, groupH);

    groups.push({
      x: cursorX,
      y: PAD_Y,
      w: groupW,
      h: groupH,
      prefix: group.prefix,
      connector: group.connector,
    });

    for (const slot of group.slots) {
      cages.push({
        x: cursorX + slot.col * (cage.w + GAP_X),
        y: PAD_Y + slot.row * (cage.h + GAP_Y),
        w: cage.w,
        h: cage.h,
        id: slot.id,
        index: slot.index,
        ports: slot.ports,
        connector: group.connector,
        groupIndex,
      });
    }

    cursorX += groupW + GROUP_GAP;
  });

  const innerH = maxGroupH + LABEL_H;
  const width = cursorX - GROUP_GAP + PAD_X;
  const height = innerH + PAD_Y * 2;

  // Groups shorter than the tallest (uplinks beside a two-row bank) are centred
  // vertically, which is how mixed-height banks sit on a real panel.
  for (const group of groups) {
    const shift = (maxGroupH - group.h) / 2;
    if (shift > 0) {
      group.y += shift;
      for (const c of cages) {
        if (groups[c.groupIndex] === group) c.y += shift;
      }
    }
  }

  return {
    width,
    height,
    chassis: { x: 0, y: 0, w: width, h: height },
    brand: { x: PAD_X, y: PAD_Y, w: BRAND_W, h: innerH - LABEL_H },
    groups,
    cages,
  };
}
