import { describe, expect, it } from 'vitest';
import {
  classifyConnector,
  deriveFaceplate,
  isBrokenOut,
  parsePortName,
  rowsFor,
} from './faceplate';
import type { Port } from '@/models';

function port(name: string, speed_mbps: number | null = 1000): Port {
  return {
    device_id: 'd1',
    name,
    index: 0,
    state: 'up',
    admin_up: true,
    link_up: true,
    speed_mbps,
    duplex: 'full',
    mac: null,
    mtu: 9216,
    untagged_vlan: 1,
    tagged_vlans: [],
    description: '',
    host_model: '',
    bmc_ip: '',
    notes: '',
    services: {},
    rx_bytes: null,
    tx_bytes: null,
    traffic: 0,
    last_change: 0,
  };
}

/** leaf-01, read from the live API: 32x QSFP at 40G/100G. */
const LEAF01: Port[] = Array.from({ length: 32 }, (_, i) =>
  port(`xe-1/1/${i + 1}`, i % 2 === 0 ? 100000 : 40000),
);

/**
 * swos-css326, modelled on the live API: 24 copper + 2 SFP+, where port names
 * carry operator-written labels after the index. Labels are anonymised here —
 * the real device has host/owner text in them — but the SHAPE is exactly what
 * the parser has to survive: `Port<n>-<free text containing digits>`.
 */
const SWOS: Port[] = [
  port('Port1-host-a-BMC-16', 1000),
  port('Port2-host-b-240', 1000),
  ...Array.from({ length: 21 }, (_, i) => port(`Port${i + 3}-11${i % 7}`, 1000)),
  port('Port24-114', 1000),
  port('SFP1', 10000),
  port('SFP2-111', 10000),
];

describe('parsePortName', () => {
  it('parses structural slash names', () => {
    expect(parsePortName('xe-1/1/5')).toEqual({
      prefix: 'xe-1/1',
      index: 5,
      lane: null,
      cageId: 'xe-1/1/5',
    });
  });

  it('reads the index from the FIRST numeric run, not the last', () => {
    // Real SwOS name. The trailing 16 is operator text, not the port number.
    expect(parsePortName('Port1-host-a-BMC-16')).toEqual({
      prefix: 'Port',
      index: 1,
      lane: null,
      cageId: 'Port1-host-a-BMC-16',
    });
  });

  it('parses a bare prefixed name', () => {
    expect(parsePortName('SFP1')).toMatchObject({ prefix: 'SFP', index: 1, lane: null });
  });

  it('parses a labelled uplink', () => {
    expect(parsePortName('SFP2-111')).toMatchObject({ prefix: 'SFP', index: 2 });
  });

  it('splits PicOS colon breakout lanes off the cage id', () => {
    expect(parsePortName('xe-1/1/5:2')).toEqual({
      prefix: 'xe-1/1',
      index: 5,
      lane: 2,
      cageId: 'xe-1/1/5',
    });
  });

  it('splits dotted breakout lanes', () => {
    expect(parsePortName('xe-1/1/5.3')).toMatchObject({ index: 5, lane: 3, cageId: 'xe-1/1/5' });
  });

  it('returns null when there is no index at all', () => {
    expect(parsePortName('mgmt')).toBeNull();
  });
});

describe('classifyConnector', () => {
  it('uses the group maximum, so a down port does not misclassify its cage', () => {
    // One port negotiated 1G, another 100G: the cage is QSFP.
    expect(classifyConnector('xe-1/1', [1000, null, 100000])).toBe('qsfp');
  });

  it('maps speed tiers', () => {
    expect(classifyConnector('Port', [1000])).toBe('rj45');
    expect(classifyConnector('x', [10000])).toBe('sfp');
    expect(classifyConnector('x', [25000])).toBe('sfp28');
    expect(classifyConnector('x', [40000])).toBe('qsfp');
  });

  it('trusts an explicit media prefix over missing speed', () => {
    // Unplugged SFP reports no speed but is still a fibre cage.
    expect(classifyConnector('SFP', [null, null])).toBe('sfp');
    expect(classifyConnector('QSFP', [])).toBe('qsfp');
  });

  it('falls back to vendor naming when there is no speed', () => {
    expect(classifyConnector('xe-1/1', [null])).toBe('sfp');
    expect(classifyConnector('Port', [null])).toBe('rj45');
  });
});

describe('rowsFor', () => {
  it('keeps small uplink groups on one row', () => {
    expect(rowsFor(2)).toBe(1);
    expect(rowsFor(6)).toBe(1);
  });

  it('stacks normal port banks two high', () => {
    expect(rowsFor(24)).toBe(2);
    expect(rowsFor(32)).toBe(2);
  });

  it('goes four high for very dense panels', () => {
    expect(rowsFor(96)).toBe(4);
  });
});

describe('deriveFaceplate — leaf-01 (pica8, real inventory)', () => {
  const fp = deriveFaceplate(LEAF01);

  it('is one QSFP group of 32, not the sfp-48 stereotype', () => {
    expect(fp.source).toBe('discovered');
    expect(fp.groups).toHaveLength(1);
    expect(fp.groups[0].connector).toBe('qsfp');
    expect(fp.groups[0].slots).toHaveLength(32);
  });

  it('lays 32 cages out as 2x16', () => {
    expect(fp.groups[0].rows).toBe(2);
    expect(fp.groups[0].cols).toBe(16);
  });

  it('numbers odd on the top row and even on the bottom', () => {
    const g = fp.groups[0];
    const byId = (id: string) => g.slots.find((s) => s.id === id)!;
    expect(byId('xe-1/1/1')).toMatchObject({ row: 0, col: 0 });
    expect(byId('xe-1/1/2')).toMatchObject({ row: 1, col: 0 });
    expect(byId('xe-1/1/3')).toMatchObject({ row: 0, col: 1 });
    expect(byId('xe-1/1/32')).toMatchObject({ row: 1, col: 15 });
  });

  it('groups by the structural prefix', () => {
    expect(fp.groups[0].prefix).toBe('xe-1/1');
  });
});

describe('deriveFaceplate — swos-css326 (real inventory)', () => {
  const fp = deriveFaceplate(SWOS);

  it('splits into copper access ports and fibre uplinks', () => {
    expect(fp.groups).toHaveLength(2);
    expect(fp.groups.map((g) => g.prefix)).toEqual(['Port', 'SFP']);
  });

  it('classifies each group by its own media', () => {
    expect(fp.groups[0].connector).toBe('rj45');
    expect(fp.groups[1].connector).toBe('sfp');
  });

  it('lays 24 copper ports out as 2x12 and 2 uplinks on one row', () => {
    expect(fp.groups[0]).toMatchObject({ rows: 2, cols: 12 });
    expect(fp.groups[0].slots).toHaveLength(24);
    expect(fp.groups[1]).toMatchObject({ rows: 1, cols: 2 });
  });

  it('orders slots by parsed index, ignoring operator labels in the name', () => {
    const first = fp.groups[0].slots[0];
    expect(first.index).toBe(1);
    expect(first.id).toBe('Port1-host-a-BMC-16');
  });

  it('puts uplinks after access ports, matching the physical panel', () => {
    expect(fp.groups[1].slots.map((s) => s.index)).toEqual([1, 2]);
  });
});

describe('deriveFaceplate — breakout (PCS lanes)', () => {
  const broken: Port[] = [
    port('xe-1/1/1', 100000),
    port('xe-1/1/2:1', 25000),
    port('xe-1/1/2:2', 25000),
    port('xe-1/1/2:3', 25000),
    port('xe-1/1/2:4', 25000),
    port('xe-1/1/3', 100000),
  ];
  const fp = deriveFaceplate(broken);

  it('collapses four lanes into ONE physical cage', () => {
    // 6 logical ports, 3 physical cages. Drawing 6 rectangles would be wrong,
    // and over-running the grid is what crashed the 3D renderer.
    expect(fp.portCount).toBe(6);
    expect(fp.slotCount).toBe(3);
  });

  it('keeps every lane reachable from its cage', () => {
    const cage = fp.groups[0].slots.find((s) => s.id === 'xe-1/1/2')!;
    expect(cage.ports.map((p) => p.name)).toEqual([
      'xe-1/1/2:1',
      'xe-1/1/2:2',
      'xe-1/1/2:3',
      'xe-1/1/2:4',
    ]);
    expect(isBrokenOut(cage)).toBe(true);
  });

  it('does not mark an unsplit cage as broken out', () => {
    const cage = fp.groups[0].slots.find((s) => s.id === 'xe-1/1/1')!;
    expect(isBrokenOut(cage)).toBe(false);
  });
});

describe('deriveFaceplate — degenerate input', () => {
  it('marks an empty port list as a platform fallback, never as fact', () => {
    const fp = deriveFaceplate([], 'qsfp-32');
    expect(fp.source).toBe('platform-fallback');
    expect(fp.groups[0]).toMatchObject({ rows: 2, cols: 16, connector: 'qsfp' });
    expect(fp.slotCount).toBe(0);
  });

  it('returns an empty faceplate when there is nothing to fall back to', () => {
    expect(deriveFaceplate([])).toMatchObject({ groups: [], source: 'platform-fallback' });
  });

  it('keeps unparseable port names instead of dropping them', () => {
    // Hiding a port the operator has would repeat the exact bug this design
    // exists to prevent.
    const fp = deriveFaceplate([port('mgmt', 1000), port('console', null)]);
    expect(fp.portCount).toBe(2);
    expect(fp.slotCount).toBe(2);
  });
});
