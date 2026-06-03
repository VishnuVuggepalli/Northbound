import { describe, expect, it } from 'vitest';
import { buildPortConfigPatch, parseTagged, sameSet } from './portConfigPatch';
import type { Port } from '@/types';

function port(over: Partial<Port> = {}): Port {
  return {
    device_id: 'd1',
    name: 'xe-1/1/1',
    index: 1,
    state: 'up',
    admin_up: true,
    link_up: true,
    speed_mbps: 10000,
    duplex: 'full',
    mac: null,
    mtu: 9216,
    untagged_vlan: 1010,
    tagged_vlans: [1002],
    description: '',
    host_model: '',
    bmc_ip: '',
    notes: '',
    services: {},
    traffic: 0,
    last_change: 0,
    ...over,
  };
}

describe('buildPortConfigPatch', () => {
  it('REGRESSION: native-only change on a trunk keeps trunk + tagged (sends port_mode)', () => {
    const p = port({ untagged_vlan: 1010, tagged_vlans: [1002] });
    const patch = buildPortConfigPatch(p, {
      mode: 'trunk',
      native: 1011,
      tagged: [1002],
      mtu: p.mtu,
      enabled: true,
    });
    // Must carry the mode so the backend does NOT infer access and wipe tagged.
    expect(patch.port_mode).toBe('trunk');
    expect(patch.untagged_vlan).toBe(1011);
    // tagged unchanged → omitted (device merge keeps existing members).
    expect('tagged_vlans' in patch).toBe(false);
  });

  it('no changes → empty patch', () => {
    const p = port();
    expect(buildPortConfigPatch(p, { mode: 'trunk', native: 1010, tagged: [1002], mtu: 9216, enabled: true })).toEqual({});
  });

  it('changing tagged set sends mode + the new set', () => {
    const p = port({ tagged_vlans: [1002] });
    const patch = buildPortConfigPatch(p, { mode: 'trunk', native: 1010, tagged: [1002, 1003], mtu: 9216, enabled: true });
    expect(patch.port_mode).toBe('trunk');
    expect(patch.tagged_vlans).toEqual([1002, 1003]);
  });

  it('trunk → access carries mode + native, drops tagged from the patch', () => {
    const p = port({ untagged_vlan: 1010, tagged_vlans: [1002, 1003] });
    const patch = buildPortConfigPatch(p, { mode: 'access', native: 1010, tagged: [], mtu: 9216, enabled: true });
    expect(patch.port_mode).toBe('access');
    expect(patch.untagged_vlan).toBe(1010);
    expect('tagged_vlans' in patch).toBe(false); // tagged only sent in trunk mode
  });

  it('mtu/enabled-only changes do not add port_mode', () => {
    const p = port();
    const patch = buildPortConfigPatch(p, { mode: 'trunk', native: 1010, tagged: [1002], mtu: 1500, enabled: false });
    expect(patch).toEqual({ mtu: 1500, enabled: false });
    expect('port_mode' in patch).toBe(false);
  });
});

describe('parseTagged / sameSet', () => {
  it('parses, dedupes, sorts, drops invalid', () => {
    expect(parseTagged('1003, 1002, 1002, x, 5000, 20')).toEqual([20, 1002, 1003]);
  });
  it('sameSet is order-insensitive', () => {
    expect(sameSet([1, 2, 3], [3, 2, 1])).toBe(true);
    expect(sameSet([1, 2], [1, 2, 3])).toBe(false);
  });
});
