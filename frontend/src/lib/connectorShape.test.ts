import { describe, expect, it } from 'vitest';
import { connectorParts, RJ45_CONTACTS, type ShapeBox } from './connectorShape';
import type { ConnectorType } from './faceplate';

const KINDS: ConnectorType[] = ['rj45', 'sfp', 'sfp28', 'qsfp', 'unknown'];
const BOX: ShapeBox = { x: 10, y: 20, w: 30, h: 26 };

/** Every drawn point of a part, for containment checks. */
function extremes(part: ReturnType<typeof connectorParts>[number]) {
  if (part.kind === 'rect') {
    return [
      [part.x, part.y],
      [part.x + part.w, part.y + part.h],
    ];
  }
  if (part.kind === 'line') {
    return [
      [part.x1, part.y1],
      [part.x2, part.y2],
    ];
  }
  // Path: pull every absolute coordinate pair out of the `M` command plus the
  // running position implied by the relative h/v steps.
  const nums = part.d.match(/-?\d+(\.\d+)?/g)!.map(Number);
  let [cx, cy] = [nums[0], nums[1]];
  const pts: number[][] = [[cx, cy]];
  const cmds = part.d.match(/[hv]-?\d+(\.\d+)?/g) ?? [];
  for (const c of cmds) {
    const v = Number(c.slice(1));
    if (c[0] === 'h') cx += v;
    else cy += v;
    pts.push([cx, cy]);
  }
  return pts;
}

describe('connectorParts', () => {
  it('produces geometry for every connector kind', () => {
    for (const kind of KINDS) {
      expect(connectorParts(kind, BOX).length).toBeGreaterThan(0);
    }
  });

  it('keeps every part inside the caller box', () => {
    // A part escaping its box would collide with the neighbouring cage on the
    // faceplate, where cages are only GAP_X apart.
    for (const kind of KINDS) {
      for (const part of connectorParts(kind, BOX)) {
        for (const [px, py] of extremes(part)) {
          expect(px).toBeGreaterThanOrEqual(BOX.x - 2); // bale reaches slightly left
          expect(px).toBeLessThanOrEqual(BOX.x + BOX.w);
          expect(py).toBeGreaterThanOrEqual(BOX.y);
          expect(py).toBeLessThanOrEqual(BOX.y + BOX.h);
        }
      }
    }
  });

  it('gives RJ45 a keyed mouth plus a full 8P8C contact block', () => {
    const parts = connectorParts('rj45', BOX);
    expect(parts.filter((p) => p.role === 'contact')).toHaveLength(RJ45_CONTACTS);
    const mouth = parts.find((p) => p.role === 'mouth')!;
    expect(mouth.kind).toBe('path');
  });

  it('gives QSFP a divider rib and SFP none — the only thing telling them apart', () => {
    expect(connectorParts('qsfp', BOX).some((p) => p.role === 'rib')).toBe(true);
    expect(connectorParts('sfp', BOX).some((p) => p.role === 'rib')).toBe(false);
  });

  it('gives every transceiver a latch bale', () => {
    for (const kind of ['sfp', 'sfp28', 'qsfp'] as const) {
      expect(connectorParts(kind, BOX).some((p) => p.role === 'bale')).toBe(true);
    }
  });

  it('treats sfp28 as SFP-shaped', () => {
    const a = connectorParts('sfp', BOX);
    const b = connectorParts('sfp28', BOX);
    expect(JSON.stringify(b)).toBe(JSON.stringify(a));
  });

  it('never dresses unknown media as a known connector', () => {
    const parts = connectorParts('unknown', BOX);
    expect(parts.every((p) => p.role === 'mouth')).toBe(true);
    expect(parts.some((p) => p.role === 'contact' || p.role === 'rib')).toBe(false);
  });

  it('scales proportionally — the glyph and the panel draw the same shape', () => {
    // This is the property the shared module exists to guarantee: doubling the
    // box doubles every offset, so a 24px icon and a 30-unit cage cannot drift.
    const small = connectorParts('rj45', { x: 0, y: 0, w: 10, h: 10 });
    const big = connectorParts('rj45', { x: 0, y: 0, w: 20, h: 20 });
    const sc = small.filter((p) => p.kind === 'rect')[0] as { x: number; w: number };
    const bc = big.filter((p) => p.kind === 'rect')[0] as { x: number; w: number };
    expect(bc.x).toBeCloseTo(sc.x * 2, 6);
    expect(bc.w).toBeCloseTo(sc.w * 2, 6);
  });

  it('translates with the box origin', () => {
    const at0 = connectorParts('sfp', { x: 0, y: 0, w: 30, h: 20 });
    const at100 = connectorParts('sfp', { x: 100, y: 50, w: 30, h: 20 });
    const a = at0.find((p) => p.role === 'mouth') as { x: number; y: number };
    const b = at100.find((p) => p.role === 'mouth') as { x: number; y: number };
    expect(b.x - a.x).toBeCloseTo(100, 6);
    expect(b.y - a.y).toBeCloseTo(50, 6);
  });
});
