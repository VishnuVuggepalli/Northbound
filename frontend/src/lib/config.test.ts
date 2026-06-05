import { describe, expect, it } from 'vitest';
import {
  applyChangeToPort,
  mergeChange,
  portToRequestedChanges,
  renderConfigSnippet,
  renderFullConfig,
} from './config';
import type { Device, Port } from '@/models';

const device: Device = {
  id: 'd1',
  name: 'lab-leaf-1',
  env: 'lab',
  platform: 'cisco',
  role: 'leaf',
  mgmt_ip: '10.10.0.11',
  model: 'Catalyst 9300-24T',
  portCount: 24,
  portKind: 'rj45-24-2sfp',
  reachable: true,
};

const port: Port = {
  device_id: 'd1',
  name: 'Ethernet1',
  index: 0,
  state: 'up',
  admin_up: true,
  link_up: true,
  speed_mbps: 1000,
  duplex: 'full',
  mac: 'aa:bb:cc:dd:ee:ff',
  mtu: 1500,
  untagged_vlan: 100,
  tagged_vlans: [200],
  description: 'VLAN-100 | Dell R740 | 10.0.0.55',
  host_model: 'Dell R740',
  bmc_ip: '10.0.0.55',
  notes: '',
  services: { lldp: true, stp: true, mstp: false, lacp: false, bgp: false, ospf: false, erspan: false },
  traffic: 0.4,
  last_change: 0,
};

describe('config helpers', () => {
  it('mergeChange picks change values over port values', () => {
    const merged = mergeChange(port, { untagged_vlan: 200 });
    expect(merged.untagged_vlan).toBe(200);
    expect(merged.host_model).toBe('Dell R740');
  });

  it('applyChangeToPort regenerates description when full set provided', () => {
    const next = applyChangeToPort(port, {
      untagged_vlan: 300,
      host_model: 'HPE DL380',
      bmc_ip: '10.0.1.10',
    });
    expect(next.description).toBe('VLAN-300 | HPE DL380 | 10.0.1.10');
  });

  it('portToRequestedChanges returns a stable copy', () => {
    const out = portToRequestedChanges(port);
    expect(out.untagged_vlan).toBe(100);
    expect(out.tagged_vlans).toEqual([200]);
    expect(out.tagged_vlans).not.toBe(port.tagged_vlans);
  });

  it('renderConfigSnippet emits Cisco IOS-flavored commands', () => {
    const snippet = renderConfigSnippet(device, port);
    expect(snippet).toContain('interface Ethernet1');
    // port has a tagged vlan (200), so it renders as a trunk with native vlan 100.
    expect(snippet).toContain('switchport trunk native vlan 100');
  });

  it('renderFullConfig produces multiple lines', () => {
    const lines = renderFullConfig(device, [port]);
    expect(lines.length).toBeGreaterThan(5);
    expect(lines.join('\n')).toContain(port.name);
  });
});
