import { describe, expect, it } from 'vitest';
import {
  changeKindLabel,
  hasUnresolvedPortReference,
  isDeviceLevel,
  summarizeChange,
} from './changeSummary';
import type { ChangeKind, ChangeRequest } from '@/models';

/**
 * Fixtures are REAL payloads read out of the live northbound.db on ovsovn, not
 * invented shapes — including the explicit `null`s the backend emits for unset
 * optional fields.
 */
function req(
  kind: ChangeKind,
  change_params: Record<string, unknown>,
  over: Partial<ChangeRequest> = {},
): ChangeRequest {
  return {
    id: 'r1',
    device_id: 'd1',
    port_name: kind === 'port' ? 'xe-1/1/5' : '',
    requested_by: 'u1',
    requested_by_username: 'admin1',
    kind,
    change_params,
    requested_changes: {},
    reason: 'because',
    status: 'pending',
    reviewer_id: null,
    reviewer_comment: '',
    created_at: 0,
    reviewed_at: null,
    applied_at: null,
    ...over,
  };
}

describe('summarizeChange', () => {
  it('summarizes a vlan create', () => {
    const s = summarizeChange(req('vlan', { action: 'create', vlan_id: 1234, name: 'verify-slice' }));
    expect(s.target).toBe('VLAN 1234');
    expect(s.action).toBe('create');
    expect(s.details).toEqual([{ label: 'name', value: 'verify-slice' }]);
  });

  it('summarizes an l3 SVI create and does not confuse `kind` with the discriminator', () => {
    const s = summarizeChange(
      req('l3', {
        action: 'create',
        kind: 'svi',
        name: null,
        vlan_id: 3997,
        ipv4: '192.0.2.1/30',
        mtu: null,
        enabled: null,
        dhcp: null,
      }),
    );
    // `kind: 'svi'` is the interface kind, NOT the change kind.
    expect(s.target).toBe('SVI vlan3997');
    expect(s.action).toBe('create');
    expect(s.details).toEqual([{ label: 'ipv4', value: '192.0.2.1/30' }]);
  });

  it('uses the explicit name for a loopback and surfaces the vrf binding', () => {
    const s = summarizeChange(
      req('l3', {
        action: 'create',
        kind: 'loopback',
        name: 'lo1',
        vlan_id: null,
        ipv4: '192.0.2.9/32',
        vrf: 'nb-bindtest',
      }),
    );
    expect(s.target).toBe('LOOPBACK lo1');
    expect(s.details).toEqual([
      { label: 'ipv4', value: '192.0.2.9/32' },
      { label: 'vrf', value: 'nb-bindtest' },
    ]);
  });

  it('summarizes a vrf create', () => {
    const s = summarizeChange(
      req('vrf', { action: 'create', name: 'nb-test-vrf', description: 'northbound live-validate' }),
    );
    expect(s.target).toBe('VRF nb-test-vrf');
    expect(s.details).toEqual([{ label: 'description', value: 'northbound live-validate' }]);
  });

  it('summarizes an ospf interface set', () => {
    const s = summarizeChange(
      req('ospf', {
        action: 'set',
        target: 'interface',
        router_id: null,
        interface: 'vlan1010',
        area: '0.0.0.0',
        cost: null,
        hello_interval: null,
        dead_interval: null,
        passive: null,
      }),
    );
    expect(s.target).toBe('OSPF vlan1010');
    expect(s.action).toBe('set');
    expect(s.details).toEqual([{ label: 'area', value: '0.0.0.0' }]);
  });

  it('summarizes the legacy port shape', () => {
    const s = summarizeChange(
      req('port', {
        untagged_vlan: 1070,
        tagged_vlans: [1002, 1071, 1072],
        host_model: 'Dell',
        bmc_ip: '172.18.100.111',
        notes: '',
        description: null,
        port_mode: null,
        mtu: null,
        enabled: null,
      }),
    );
    expect(s.details).toEqual([
      { label: 'untagged', value: '1070' },
      { label: 'tagged', value: '1002, 1071, 1072' },
      { label: 'host', value: 'Dell' },
      { label: 'bmc', value: '172.18.100.111' },
    ]);
  });

  it('omits null/empty fields rather than rendering blanks', () => {
    const s = summarizeChange(req('vlan', { action: 'delete', vlan_id: 3997, name: null, description: null }));
    expect(s.details).toEqual([]);
    expect(s.target).toBe('VLAN 3997');
  });

  it('degrades gracefully when the payload is empty', () => {
    const s = summarizeChange(req('vlan', {}));
    expect(s.target).toBe('VLAN');
    expect(s.action).toBe('');
    expect(s.details).toEqual([]);
  });
});

describe('isDeviceLevel', () => {
  it('is true for every non-port kind', () => {
    for (const k of ['vlan', 'l3', 'vrf', 'ospf'] as const) {
      expect(isDeviceLevel(req(k, {}))).toBe(true);
    }
  });

  it('is false for a port change', () => {
    expect(isDeviceLevel(req('port', {}))).toBe(false);
  });
});

describe('hasUnresolvedPortReference', () => {
  it('flags a port request whose pinned port no longer resolves', () => {
    expect(hasUnresolvedPortReference(req('port', {}), undefined)).toBe(true);
  });

  it('does not flag a port request whose pinned port resolves', () => {
    expect(hasUnresolvedPortReference(req('port', {}), { name: 'xe-1/1/5' })).toBe(false);
  });

  it('never flags a device-level request — an absent port is expected, not drift', () => {
    expect(hasUnresolvedPortReference(req('vlan', {}), undefined)).toBe(false);
  });
});

describe('changeKindLabel', () => {
  it('maps kinds to display labels', () => {
    expect(changeKindLabel('vlan')).toBe('VLAN');
    expect(changeKindLabel('l3')).toBe('L3');
    expect(changeKindLabel('port')).toBe('Port');
  });
});
