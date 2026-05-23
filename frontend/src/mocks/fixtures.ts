/**
 * Northbound — mock fixtures
 *
 * Direct port of `supporting material/data.jsx` into TypeScript. The mock
 * generator is deterministic (mulberry32 with a fixed seed) so reloads always
 * produce the same data. The shapes match `src/types/index.ts` exactly so the
 * mock client and the future real client are interchangeable.
 */

import type {
  AuditEntry,
  ChangeRequest,
  Device,
  Neighbor,
  Port,
  PortMap,
  PortServices,
  TopologyLink,
  User,
} from '@/types';

const HOST_MODELS = [
  'Dell R740',
  'Dell R650',
  'Supermicro X11',
  'Supermicro X12',
  'HPE DL380 G10',
  'HPE DL360',
  'Lenovo SR650',
  'Custom 1U build',
] as const;

export const VLANS: readonly number[] = [10, 20, 100, 200, 300, 999];

/**
 * mulberry32 — deterministic, fast, seeded. Same as the prototype so the
 * generated values line up if anyone cross-references screenshots.
 */
function mulberry32(seed: number): () => number {
  let t = seed >>> 0;
  return () => {
    t = (t + 0x6d2b79f5) >>> 0;
    let r = t;
    r = Math.imul(r ^ (r >>> 15), r | 1);
    r ^= r + Math.imul(r ^ (r >>> 7), r | 61);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(arr: readonly T[], rng: () => number): T {
  return arr[Math.floor(rng() * arr.length)] as T;
}

export const DEVICES: readonly Device[] = [
  { id: 'd-lab-leaf-1', name: 'lab-leaf-1', env: 'lab', platform: 'mikrotik', role: 'leaf', mgmt_ip: '10.10.0.11', model: 'CRS326-24G-2S+', portCount: 24, portKind: 'rj45-24-2sfp', reachable: true },
  { id: 'd-lab-leaf-2', name: 'lab-leaf-2', env: 'lab', platform: 'mikrotik', role: 'leaf', mgmt_ip: '10.10.0.12', model: 'CRS326-24G-2S+', portCount: 24, portKind: 'rj45-24-2sfp', reachable: true },
  { id: 'd-lab-leaf-3', name: 'lab-leaf-3', env: 'lab', platform: 'mikrotik', role: 'leaf', mgmt_ip: '10.10.0.13', model: 'CRS326-24G-2S+', portCount: 24, portKind: 'rj45-24-2sfp', reachable: false },
  // SwOS device — same broad platform as RouterOS leaves; the model string
  // disambiguates via findPlatformForDevice (model =~ /swos/i).
  { id: 'd-lab-swos-1', name: 'lab-swos-1', env: 'lab', platform: 'mikrotik', role: 'leaf', mgmt_ip: '10.10.0.15', model: 'CRS112-8G-4S (SwOS)', portCount: 5, portKind: 'sfp-5', reachable: true },
  { id: 'd-lab-spine-1', name: 'lab-spine-1', env: 'lab', platform: 'mikrotik', role: 'spine', mgmt_ip: '10.10.0.10', model: 'CRS305', portCount: 5, portKind: 'sfp-5', reachable: true },
  { id: 'd-lab-rtr-1', name: 'lab-rtr-1', env: 'lab', platform: 'freebsd', role: 'router', mgmt_ip: '10.10.0.1', model: 'FreeBSD 14.0', portCount: 4, portKind: 'rj45-4', reachable: true, ssh_user: 'root' },
  { id: 'd-dc-arista-1', name: 'dc-arista-1', env: 'dc', platform: 'arista', role: 'leaf', mgmt_ip: '10.20.0.11', model: '7050X3-32S 100G', portCount: 32, portKind: 'qsfp-32', reachable: true },
  { id: 'd-dc-pica-10g', name: 'dc-pica-10g', env: 'dc', platform: 'pica8', role: 'leaf', mgmt_ip: '10.20.0.12', model: 'PicOS 48×10G', portCount: 48, portKind: 'sfp-48', reachable: true },
  { id: 'd-dc-pica-100g', name: 'dc-pica-100g', env: 'dc', platform: 'pica8', role: 'spine', mgmt_ip: '10.20.0.13', model: 'PicOS 32×100G', portCount: 32, portKind: 'qsfp-32', reachable: true },
  { id: 'd-dc-rtr-1', name: 'dc-rtr-1', env: 'dc', platform: 'freebsd', role: 'router', mgmt_ip: '10.20.0.1', model: 'FreeBSD 14.0 + FRR', portCount: 4, portKind: 'rj45-4', reachable: true, ssh_user: 'root' },
  { id: 'd-dc-vpn-1', name: 'dc-vpn-1', env: 'dc', platform: 'freebsd', role: 'vpn', mgmt_ip: '10.20.0.2', model: 'WireGuard node', portCount: 4, portKind: 'rj45-4', reachable: true, ssh_user: 'root' },
];

/**
 * Pre-baked LLDP neighbor fixtures. We seed a handful of representative ports
 * across both environments so the PortPanel Neighbor row has something to
 * render. SwOS device gets neighbors too — it supports LLDP via SNMP.
 *
 * Shape matches the canonical `Neighbor` from `_lib/lldp.py` (chassis_id as
 * a MAC string, port_id as the remote's port name, system_name FQDN or '—').
 */
const NEIGHBORS_BY_DEVICE: Record<string, Record<string, Neighbor[]>> = {
  'd-lab-leaf-1': {
    ether1: [
      {
        chassis_id: '64:d1:54:a3:00:01',
        port_id: 'sfp-sfpplus1',
        system_name: 'lab-spine-1',
        system_description: 'MikroTik CRS305 RouterOS 7.14',
      },
    ],
    ether14: [
      {
        chassis_id: 'aa:bb:cc:00:14:01',
        port_id: 'eno1',
        system_name: 'host-104.lab.local',
        system_description: 'Linux 6.6 (Dell R740)',
      },
    ],
  },
  'd-lab-spine-1': {
    'sfp-sfpplus1': [
      {
        chassis_id: '64:d1:54:a1:11:01',
        port_id: 'ether1',
        system_name: 'lab-leaf-1',
        system_description: 'MikroTik CRS326 RouterOS 7.14',
      },
    ],
    'sfp-sfpplus2': [
      {
        chassis_id: '64:d1:54:a1:11:02',
        port_id: 'ether1',
        system_name: 'lab-leaf-2',
        system_description: 'MikroTik CRS326 RouterOS 7.14',
      },
    ],
  },
  'd-lab-swos-1': {
    'sfp-sfpplus1': [
      {
        chassis_id: '64:d1:54:a3:00:01',
        port_id: 'sfp-sfpplus3',
        system_name: 'lab-spine-1',
        system_description: 'MikroTik CRS305 RouterOS 7.14',
      },
    ],
  },
  'd-dc-arista-1': {
    'Ethernet1/1': [
      {
        chassis_id: '74:83:ef:00:c0:01',
        port_id: 'hu-1/1/1',
        system_name: 'dc-pica-100g',
        system_description: 'Pica8 PicOS 4.x',
      },
    ],
    'Ethernet7/1': [
      {
        chassis_id: 'aa:bb:cc:dc:07:01',
        port_id: 'eth0',
        system_name: 'k8s-worker-7.dc.local',
        system_description: 'Linux (Supermicro X12)',
      },
    ],
  },
  'd-dc-pica-10g': {
    'te-1/1/1': [
      {
        chassis_id: '74:83:ef:00:c0:02',
        port_id: 'hu-1/1/2',
        system_name: 'dc-pica-100g',
        system_description: 'Pica8 PicOS 4.x',
      },
    ],
  },
};

function neighborsFor(deviceId: string, portName: string): Neighbor[] | undefined {
  return NEIGHBORS_BY_DEVICE[deviceId]?.[portName];
}

export function portNameFor(device: Device, idx: number): string {
  switch (device.platform) {
    case 'mikrotik':
      if (device.role === 'spine') return `sfp-sfpplus${idx + 1}`;
      if (idx < 24) return `ether${idx + 1}`;
      return `sfp-sfpplus${idx - 23}`;
    case 'arista':
      return `Ethernet${idx + 1}/1`;
    case 'pica8':
      return device.portCount === 48 ? `te-1/1/${idx + 1}` : `hu-1/1/${idx + 1}`;
    case 'freebsd': {
      const names = ['igb0', 'igb1', 'ix0', 'ix1'];
      return names[idx] ?? `igb${idx}`;
    }
    default:
      return `port${idx + 1}`;
  }
}

function speedFor(device: Device, state: Port['state']): number | null {
  if (state !== 'up') return null;
  if (device.portKind.startsWith('qsfp')) return 100000;
  if (device.portKind.startsWith('sfp')) return 10000;
  return 1000;
}

function generatePorts(): PortMap {
  const r = mulberry32(7);
  const map: PortMap = {};
  for (const device of DEVICES) {
    const ports: Port[] = [];
    for (let i = 0; i < device.portCount; i++) {
      const v = r();
      let state: Port['state'];
      if (v < 0.7) state = 'up';
      else if (v < 0.85) state = 'down';
      else state = 'disabled';

      const untagged = pick(VLANS, r);
      const tagged = r() < 0.18 ? VLANS.filter((x) => x !== untagged && r() < 0.35) : [];
      const hasMeta = state === 'up' && r() < 0.5;
      const hostModel = hasMeta ? pick(HOST_MODELS, r) : '';
      const bmcIp = hasMeta ? `10.0.${Math.floor(r() * 4)}.${10 + Math.floor(r() * 240)}` : '';
      const description = hasMeta ? `VLAN-${untagged} | ${hostModel} | ${bmcIp}` : '';

      const services: PortServices = {
        lldp: r() < 0.9,
        stp: device.role !== 'router' && r() < 0.7,
        mstp: false,
        lacp: r() < 0.1,
        bgp: device.role === 'router' && i < 2,
        ospf: false,
        erspan: false,
      };

      const mac =
        state === 'up'
          ? Array.from({ length: 6 }, () =>
              Math.floor(r() * 256)
                .toString(16)
                .padStart(2, '0'),
            ).join(':')
          : null;

      const portName = portNameFor(device, i);
      const neighbors = neighborsFor(device.id, portName);
      ports.push({
        device_id: device.id,
        name: portName,
        index: i,
        state,
        admin_up: state !== 'disabled',
        link_up: state === 'up',
        speed_mbps: speedFor(device, state),
        duplex: state === 'up' ? 'full' : null,
        mac,
        mtu: 1500,
        untagged_vlan: untagged,
        tagged_vlans: tagged,
        description,
        host_model: hostModel,
        bmc_ip: bmcIp,
        notes: '',
        services,
        traffic: state === 'up' ? r() * 0.9 + 0.05 : 0,
        last_change: Date.now() - Math.floor(r() * 1000 * 60 * 60 * 24 * 30),
        ...(neighbors ? { neighbors } : {}),
      });
    }
    map[device.id] = ports;
  }
  return map;
}

export const PORTS: PortMap = generatePorts();

export const LINKS: readonly TopologyLink[] = [
  // Lab — leaf <-> spine fiber, router <-> spine copper
  ['d-lab-spine-1', 'd-lab-leaf-1', 'fiber'],
  ['d-lab-spine-1', 'd-lab-leaf-2', 'fiber'],
  ['d-lab-spine-1', 'd-lab-leaf-3', 'fiber'],
  ['d-lab-spine-1', 'd-lab-rtr-1', 'copper'],
  // DC — backbone fiber, vpn copper
  ['d-dc-pica-100g', 'd-dc-arista-1', 'fiber'],
  ['d-dc-pica-100g', 'd-dc-pica-10g', 'fiber'],
  ['d-dc-pica-10g', 'd-dc-rtr-1', 'fiber'],
  ['d-dc-rtr-1', 'd-dc-vpn-1', 'copper'],
];

export const CHANGE_REQUESTS: readonly ChangeRequest[] = [
  {
    id: 'r-001',
    device_id: 'd-lab-leaf-1',
    port_name: 'ether14',
    requested_by: 'alice',
    requested_changes: {
      untagged_vlan: 200,
      tagged_vlans: [],
      host_model: 'Dell R740',
      bmc_ip: '10.0.0.55',
      notes: 'New tenant deploy',
    },
    reason: 'Moving the new tenant rack into VLAN 200 per ticket NB-218.',
    status: 'pending',
    reviewer_id: null,
    reviewer_comment: '',
    created_at: Date.now() - 1000 * 60 * 12,
    reviewed_at: null,
    applied_at: null,
  },
  {
    id: 'r-002',
    device_id: 'd-dc-arista-1',
    port_name: 'Ethernet7/1',
    requested_by: 'alice',
    requested_changes: {
      untagged_vlan: 100,
      tagged_vlans: [200, 300],
      host_model: 'Supermicro X12',
      bmc_ip: '10.0.1.42',
      notes: 'Trunking for k8s',
    },
    reason: 'k8s node needs trunked uplink with mgmt on 100, app on 200, storage on 300.',
    status: 'pending',
    reviewer_id: null,
    reviewer_comment: '',
    created_at: Date.now() - 1000 * 60 * 60 * 2,
    reviewed_at: null,
    applied_at: null,
  },
  {
    id: 'r-003',
    device_id: 'd-dc-pica-10g',
    port_name: 'te-1/1/24',
    requested_by: 'alice',
    requested_changes: {
      untagged_vlan: 999,
      tagged_vlans: [],
      host_model: '',
      bmc_ip: '',
      notes: 'decommission',
    },
    reason: 'Decommission — node returned to pool.',
    status: 'approved',
    reviewer_id: 'admin',
    reviewer_comment: 'Confirmed with rack ops, port is empty.',
    created_at: Date.now() - 1000 * 60 * 60 * 4,
    reviewed_at: Date.now() - 1000 * 60 * 60,
    applied_at: null,
  },
  {
    id: 'r-004',
    device_id: 'd-lab-leaf-2',
    port_name: 'ether3',
    requested_by: 'alice',
    requested_changes: {
      untagged_vlan: 20,
      tagged_vlans: [],
      host_model: 'HPE DL380 G10',
      bmc_ip: '10.0.2.13',
      notes: '',
    },
    reason: 'Replacing the existing host in this slot.',
    status: 'applied',
    reviewer_id: 'admin',
    reviewer_comment: '',
    created_at: Date.now() - 1000 * 60 * 60 * 28,
    reviewed_at: Date.now() - 1000 * 60 * 60 * 27,
    applied_at: Date.now() - 1000 * 60 * 60 * 27,
  },
  {
    id: 'r-005',
    device_id: 'd-dc-pica-100g',
    port_name: 'hu-1/1/8',
    requested_by: 'alice',
    requested_changes: {
      untagged_vlan: 300,
      tagged_vlans: [10],
      host_model: '',
      bmc_ip: '',
      notes: 'storage backbone',
    },
    reason: 'Aligning storage backbone with new VLAN plan.',
    status: 'rejected',
    reviewer_id: 'admin',
    reviewer_comment: 'Hold off — VLAN 300 plan is changing next week. Resubmit after Friday.',
    created_at: Date.now() - 1000 * 60 * 60 * 50,
    reviewed_at: Date.now() - 1000 * 60 * 60 * 48,
    applied_at: null,
  },
];

function generateAudit(): AuditEntry[] {
  const r = mulberry32(101);
  const out: AuditEntry[] = [];
  const actions = ['port.edit', 'port.vlan.set', 'port.description.set', 'port.disabled', 'port.enabled', 'request.applied'];
  for (let i = 0; i < 60; i++) {
    const device = DEVICES[Math.floor(r() * DEVICES.length)] as Device;
    const ports = PORTS[device.id] ?? [];
    const port = ports[Math.floor(r() * ports.length)] as Port;
    const action = pick(actions, r);
    let summary: string;
    if (action === 'port.vlan.set') {
      summary = `VLAN ${pick([10, 20, 100, 200, 300], r)} → ${port.untagged_vlan}`;
    } else if (action === 'port.description.set') {
      summary = 'Updated host model & BMC';
    } else if (action === 'request.applied') {
      summary = `Applied change request r-${100 + i}`;
    } else {
      summary = action;
    }
    out.push({
      id: `a-${i}`,
      device_id: device.id,
      port_name: port.name,
      user: r() < 0.7 ? 'admin' : 'alice',
      action,
      ago_minutes: Math.floor(r() * 60 * 24 * 14),
      summary,
    });
  }
  return out;
}

export const AUDIT: readonly AuditEntry[] = generateAudit();

export const USERS: readonly User[] = [
  { username: 'admin', role: 'admin', name: 'Avery Park' },
  { username: 'alice', role: 'requester', name: 'Alice Liu' },
];
