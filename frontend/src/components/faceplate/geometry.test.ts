import { describe, expect, it } from 'vitest';
import { layoutFaceplate, GAP_X, GROUP_GAP } from './geometry';
import { deriveFaceplate } from '@/lib/faceplate';
import type { Port } from '@/models';

function port(name: string, speed_mbps: number | null): Port {
  return {
    device_id: 'd1', name, index: 0, state: 'up', admin_up: true, link_up: true,
    speed_mbps, duplex: null, mac: null, mtu: 1500, untagged_vlan: 1, tagged_vlans: [],
    description: '', host_model: '', bmc_ip: '', notes: '', services: {},
    rx_bytes: null, tx_bytes: null, traffic: 0, last_change: 0,
  } as Port;
}

/** Real shapes: leaf-01 is 32x QSFP; swos is 24 copper + 2 SFP uplinks. */
const LEAF01 = Array.from({ length: 32 }, (_, i) => port(`xe-1/1/${i + 1}`, 100000));
const SWOS = [
  ...Array.from({ length: 24 }, (_, i) => port(`Port${i + 1}-lbl${i}`, 1000)),
  port('SFP1', 10000),
  port('SFP2-111', 10000),
];

describe('layoutFaceplate', () => {
  it('places every cage exactly once', () => {
    const geo = layoutFaceplate(deriveFaceplate(LEAF01));
    expect(geo.cages).toHaveLength(32);
    expect(new Set(geo.cages.map((c) => c.id)).size).toBe(32);
  });

  it('keeps odd cages on the top row and even on the bottom', () => {
    const geo = layoutFaceplate(deriveFaceplate(LEAF01));
    const p1 = geo.cages.find((c) => c.id === 'xe-1/1/1')!;
    const p2 = geo.cages.find((c) => c.id === 'xe-1/1/2')!;
    const p3 = geo.cages.find((c) => c.id === 'xe-1/1/3')!;
    expect(p2.y).toBeGreaterThan(p1.y); // port 2 below port 1
    expect(p3.y).toBe(p1.y); // port 3 back on the top row
    expect(p3.x).toBeGreaterThan(p1.x); // and one column right
  });

  it('spaces cages within a bank by GAP_X', () => {
    const geo = layoutFaceplate(deriveFaceplate(LEAF01));
    const p1 = geo.cages.find((c) => c.id === 'xe-1/1/1')!;
    const p3 = geo.cages.find((c) => c.id === 'xe-1/1/3')!;
    expect(p3.x - (p1.x + p1.w)).toBe(GAP_X);
  });

  it('separates banks by a wider gutter than the cage pitch', () => {
    const geo = layoutFaceplate(deriveFaceplate(SWOS));
    expect(geo.groups).toHaveLength(2);
    const [access, uplink] = geo.groups;
    expect(uplink.x - (access.x + access.w)).toBe(GROUP_GAP);
    expect(GROUP_GAP).toBeGreaterThan(GAP_X);
  });

  it('gives fibre uplinks a different cage size to copper', () => {
    const geo = layoutFaceplate(deriveFaceplate(SWOS));
    const copper = geo.cages.find((c) => c.connector === 'rj45')!;
    const fibre = geo.cages.find((c) => c.connector === 'sfp')!;
    expect(fibre.h).toBeLessThan(copper.h); // SFP is a letterbox
  });

  it('centres a short bank against a taller one', () => {
    // 2 uplinks in one row beside 24 copper in two rows: the uplinks should sit
    // mid-height, not pinned to the top, as on a real panel.
    const geo = layoutFaceplate(deriveFaceplate(SWOS));
    const [access, uplink] = geo.groups;
    expect(uplink.y).toBeGreaterThan(access.y);
  });

  it('sizes the drawing to enclose every cage', () => {
    for (const ports of [LEAF01, SWOS]) {
      const geo = layoutFaceplate(deriveFaceplate(ports));
      for (const c of geo.cages) {
        expect(c.x).toBeGreaterThanOrEqual(0);
        expect(c.y).toBeGreaterThanOrEqual(0);
        expect(c.x + c.w).toBeLessThanOrEqual(geo.width);
        expect(c.y + c.h).toBeLessThanOrEqual(geo.height);
      }
    }
  });

  it('never overlaps two cages', () => {
    const geo = layoutFaceplate(deriveFaceplate(SWOS));
    for (let i = 0; i < geo.cages.length; i++) {
      for (let j = i + 1; j < geo.cages.length; j++) {
        const a = geo.cages[i];
        const b = geo.cages[j];
        const disjoint =
          a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y;
        expect(disjoint).toBe(true);
      }
    }
  });

  it('carries breakout lanes on a single cage', () => {
    const geo = layoutFaceplate(
      deriveFaceplate([
        port('xe-1/1/1', 100000),
        port('xe-1/1/2:1', 25000),
        port('xe-1/1/2:2', 25000),
      ]),
    );
    expect(geo.cages).toHaveLength(2);
    expect(geo.cages.find((c) => c.id === 'xe-1/1/2')!.ports).toHaveLength(2);
  });

  it('produces an empty drawing for a device with no ports', () => {
    const geo = layoutFaceplate(deriveFaceplate([]));
    expect(geo.cages).toHaveLength(0);
    expect(geo.width).toBeGreaterThan(0);
  });
});
