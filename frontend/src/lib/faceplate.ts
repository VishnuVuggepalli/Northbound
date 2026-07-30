/**
 * Derive a switch faceplate layout from the ports a device actually reports.
 *
 * Replaces the platform stereotype in `api/mappers.ts` (`portKindFor`), which
 * guesses a fixed rows/cols from the platform string and is never refined. On
 * the only pica8 in the fleet that guess says `sfp-48` while the device reports
 * 32 QSFP ports — wrong cage type and wrong count.
 *
 * The model is the one every switch faceplate actually uses, and the one
 * Patchdocs arrives at too: ports live in GROUPS that share a name prefix and a
 * connector type, and each group is a rectangle numbered down-then-right, which
 * puts odd ports on the top row and even ports on the bottom.
 *
 * Breakout (PCS lanes) is handled here rather than in the renderer. A 40G/100G
 * cage split into 4×10G/4×25G reports several sub-interfaces for ONE physical
 * cage; drawing one rectangle per sub-interface is wrong physically and made
 * ports outnumber the faceplate grid, which crashed the old WebGL renderer's
 * instanced meshes. Here the lanes collapse back into a single slot that knows
 * it carries several ports.
 *
 * Pure: no React, no fetching. Everything is derived from the Port list.
 */

import type { Port, PortKind } from '@/models';

/** Physical cage type, inferred from the port group. */
export type ConnectorType = 'rj45' | 'sfp' | 'sfp28' | 'qsfp' | 'unknown';

/** Human label for a cage type. Lives with the type so there is one owner. */
export const CONNECTOR_LABEL: Record<ConnectorType, string> = {
  rj45: 'RJ45',
  sfp: 'SFP',
  sfp28: 'SFP28',
  qsfp: 'QSFP',
  unknown: 'Unknown connector',
};

/** One physical cage on the faceplate. Carries >1 port when broken out. */
export interface PortSlot {
  /** Physical cage identity — the port name minus any breakout lane suffix. */
  id: string;
  /** Position within its group, 1-based, taken from the port name. */
  index: number;
  /** Ports in this cage. Length > 1 means the cage is broken out into lanes. */
  ports: Port[];
  /** Zero-based grid position within the group. */
  row: number;
  col: number;
}

export interface FaceplateGroup {
  /** Shared name prefix, e.g. `xe-1/1` or `Port` or `SFP`. */
  prefix: string;
  connector: ConnectorType;
  rows: number;
  cols: number;
  slots: PortSlot[];
}

export interface Faceplate {
  groups: FaceplateGroup[];
  /**
   * `'discovered'` when built from real ports. `'platform-fallback'` when the
   * port list was empty and we fell back to the platform stereotype — callers
   * MUST render that case as visibly provisional. A guess must never be
   * presented as fact.
   */
  source: 'discovered' | 'platform-fallback';
  /** Physical cages across all groups (breakout lanes collapsed). */
  slotCount: number;
  /** Logical ports across all groups (breakout lanes counted individually). */
  portCount: number;
}

/** A port name decomposed into the parts the layout needs. */
interface ParsedName {
  /** Group key — everything before the final index. */
  prefix: string;
  /** 1-based position within the group. */
  index: number;
  /** Breakout lane, when the name addresses a sub-interface. */
  lane: number | null;
  /** Physical cage id — the name with any lane suffix removed. */
  cageId: string;
}

/**
 * Split a port name into prefix + index (+ breakout lane).
 *
 * Must tolerate operator text: the SwOS boxes report names like
 * `Port1-Ian-BMC-16`, where everything after the index is a human label. Taking
 * the LAST number in such a name would yield 16, so the index is read from the
 * first numeric run after the prefix and the remainder is discarded.
 *
 * Handled shapes:
 *   xe-1/1/5      -> prefix "xe-1/1", index 5           (structural, slashes)
 *   xe-1/1/5:2    -> prefix "xe-1/1", index 5, lane 2   (PicOS breakout)
 *   xe-1/1/5.2    -> prefix "xe-1/1", index 5, lane 2   (dotted breakout)
 *   Port12-111    -> prefix "Port",   index 12          (trailing label)
 *   SFP2-111      -> prefix "SFP",    index 2
 *   SFP1          -> prefix "SFP",    index 1
 *   eth0          -> prefix "eth",    index 0
 */
export function parsePortName(name: string): ParsedName | null {
  // Breakout lane suffix: ":N" or ".N" at the very end. Split it off first so
  // it is never mistaken for the port index.
  const laneMatch = /^(.*?)[:.](\d+)$/.exec(name);
  let base = name;
  let lane: number | null = null;
  if (laneMatch && laneMatch[1].length > 0) {
    // Only treat it as a lane when the base still ends in a number — otherwise
    // "1.5G-port" style names would lose their tail.
    if (/\d$/.test(laneMatch[1])) {
      base = laneMatch[1];
      lane = Number(laneMatch[2]);
    }
  }

  // Structural, slash-separated names: the last path segment is the index.
  const slash = /^(.*)\/(\d+)$/.exec(base);
  if (slash) {
    return { prefix: slash[1], index: Number(slash[2]), lane, cageId: base };
  }

  // Otherwise: leading non-digits are the prefix, the first numeric run is the
  // index, anything after it is an operator label and is dropped.
  const flat = /^([^\d]*)(\d+)/.exec(base);
  if (flat && flat[1].length > 0) {
    return { prefix: flat[1].replace(/[-_\s]+$/, ''), index: Number(flat[2]), lane, cageId: base };
  }

  return null;
}

/**
 * Classify a group's cage type.
 *
 * Uses the group's MAXIMUM reported speed, not per-port speed: `speed_mbps` is
 * the negotiated rate, so a down or unplugged port reports null or a lower
 * value and would misclassify its own cage. The fastest port in a group is the
 * best evidence of what the cage physically is.
 *
 * A name prefix that names the media outright wins over speed — an unplugged
 * `SFP1` reporting no speed is still a fibre cage.
 */
export function classifyConnector(prefix: string, speeds: readonly (number | null)[]): ConnectorType {
  const p = prefix.toLowerCase();
  if (p.includes('qsfp')) return 'qsfp';
  if (p.includes('sfp')) return 'sfp';

  const max = speeds.reduce<number>((m, s) => (typeof s === 'number' && s > m ? s : m), 0);
  if (max === 0) {
    // No speed anywhere in the group. Fall back to the naming convention:
    // xe/et/ge- prefixes are vendor fibre-style names, everything else copper.
    return /^(xe|et|qe)/.test(p) ? 'sfp' : p ? 'rj45' : 'unknown';
  }
  if (max <= 1000) return 'rj45';
  if (max <= 10000) return 'sfp';
  if (max <= 25000) return 'sfp28';
  return 'qsfp';
}

/**
 * Row count for a group of `n` cages.
 *
 * Switch faceplates stack ports two-high per rack unit; only small uplink
 * groups sit in a single row. 24 copper -> 2x12 and 32 QSFP -> 2x16, which is
 * how both real devices are physically built.
 */
export function rowsFor(n: number): number {
  if (n <= 6) return 1;
  if (n <= 52) return 2;
  return 4;
}

/** Stereotype fallback, used only when a device reports no ports at all. */
const FALLBACK_SHAPE: Record<PortKind, { cols: number; rows: number; connector: ConnectorType }> = {
  'rj45-24-2sfp': { cols: 12, rows: 2, connector: 'rj45' },
  'sfp-5': { cols: 5, rows: 1, connector: 'sfp' },
  'qsfp-32': { cols: 16, rows: 2, connector: 'qsfp' },
  'sfp-48': { cols: 12, rows: 4, connector: 'sfp' },
  'rj45-4': { cols: 4, rows: 1, connector: 'rj45' },
};

/**
 * Build the faceplate for a switch from its reported ports.
 *
 * Groups are ordered by the position of their first port in the input, so
 * uplinks named later (SFP1, SFP2) render to the right of the access ports —
 * matching the physical panel.
 */
export function deriveFaceplate(ports: readonly Port[], fallbackKind?: PortKind): Faceplate {
  if (ports.length === 0) {
    const shape = fallbackKind ? FALLBACK_SHAPE[fallbackKind] : undefined;
    if (!shape) {
      return { groups: [], source: 'platform-fallback', slotCount: 0, portCount: 0 };
    }
    return {
      groups: [
        { prefix: '', connector: shape.connector, rows: shape.rows, cols: shape.cols, slots: [] },
      ],
      source: 'platform-fallback',
      slotCount: 0,
      portCount: 0,
    };
  }

  // 1. Parse, and bucket by group prefix. Unparseable names get their own
  //    single-slot group rather than being dropped — a port we cannot lay out
  //    is still a port the operator has, and hiding it would repeat the bug
  //    this whole design exists to fix.
  const buckets = new Map<string, { order: number; cages: Map<string, PortSlot> }>();
  ports.forEach((port, i) => {
    const parsed = parsePortName(port.name);
    const prefix = parsed?.prefix ?? port.name;
    const cageId = parsed?.cageId ?? port.name;
    const index = parsed?.index ?? i + 1;

    let bucket = buckets.get(prefix);
    if (!bucket) {
      bucket = { order: i, cages: new Map() };
      buckets.set(prefix, bucket);
    }
    // Breakout: several sub-interfaces share one cage id and collapse into one
    // slot carrying all of them.
    const existing = bucket.cages.get(cageId);
    if (existing) {
      existing.ports.push(port);
    } else {
      bucket.cages.set(cageId, { id: cageId, index, ports: [port], row: 0, col: 0 });
    }
  });

  // 2. Lay each group out: numbered down each column, then rightwards — the
  //    classic switch panel, odd on top and even on the bottom.
  const groups: FaceplateGroup[] = [...buckets.entries()]
    .sort((a, b) => a[1].order - b[1].order)
    .map(([prefix, bucket]) => {
      const slots = [...bucket.cages.values()].sort((a, b) => a.index - b.index);
      const rows = rowsFor(slots.length);
      const cols = Math.max(1, Math.ceil(slots.length / rows));
      const positioned = slots.map((slot, i) => ({
        ...slot,
        row: i % rows,
        col: Math.floor(i / rows),
      }));
      const speeds = slots.flatMap((s) => s.ports.map((p) => p.speed_mbps));
      return {
        prefix,
        connector: classifyConnector(prefix, speeds),
        rows,
        cols,
        slots: positioned,
      };
    });

  return {
    groups,
    source: 'discovered',
    slotCount: groups.reduce((n, g) => n + g.slots.length, 0),
    portCount: ports.length,
  };
}

/** True when this cage is split into breakout lanes (PCS sub-interfaces). */
export function isBrokenOut(slot: PortSlot): boolean {
  return slot.ports.length > 1;
}
