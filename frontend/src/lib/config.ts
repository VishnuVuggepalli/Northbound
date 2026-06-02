/**
 * Per-platform config snippet rendering.
 *
 * The UI shows what would be pushed when an admin applies a change. Real
 * apply-time rendering is the backend's job (see `Driver.render_change`); the
 * frontend just shows a representative snippet so requesters can sanity-check
 * what they're asking for before submitting.
 */

import type { Device, Port, RequestedChanges } from '@/types';

export function portToRequestedChanges(p: Port): Required<RequestedChanges> {
  return {
    untagged_vlan: p.untagged_vlan,
    tagged_vlans: [...p.tagged_vlans],
    host_model: p.host_model,
    bmc_ip: p.bmc_ip,
    notes: p.notes,
  };
}

export function mergeChange(p: Port, change: RequestedChanges): Required<RequestedChanges> {
  return {
    untagged_vlan: change.untagged_vlan ?? p.untagged_vlan,
    tagged_vlans: change.tagged_vlans ?? p.tagged_vlans,
    host_model: change.host_model ?? p.host_model,
    bmc_ip: change.bmc_ip ?? p.bmc_ip,
    notes: change.notes ?? p.notes,
  };
}

export function applyChangeToPort(p: Port, change: RequestedChanges): Port {
  const merged = mergeChange(p, change);
  return {
    ...p,
    ...merged,
    description:
      merged.untagged_vlan && merged.host_model && merged.bmc_ip
        ? `VLAN-${merged.untagged_vlan} | ${merged.host_model} | ${merged.bmc_ip}`
        : p.description,
  };
}

export function renderConfigSnippet(device: Device, port: Port): string {
  const v = port.untagged_vlan;
  const tagged = port.tagged_vlans;
  const desc = port.description ?? '';
  switch (device.platform) {
    case 'cisco':
      return [
        `interface ${port.name}`,
        `   description ${desc}`,
        `   ${port.admin_up ? 'no shutdown' : 'shutdown'}`,
        `   switchport mode ${tagged.length ? 'trunk' : 'access'}`,
        tagged.length
          ? `   switchport trunk native vlan ${v}`
          : `   switchport access vlan ${v}`,
        tagged.length ? `   switchport trunk allowed vlan ${[v, ...tagged].join(',')}` : null,
      ]
        .filter(Boolean)
        .join('\n');
    case 'mock':
      return [`# mock driver`, `interface ${port.name}`, `   vlan ${v}`].join('\n');
    case 'arista':
      return [
        `interface ${port.name}`,
        `   description ${desc}`,
        `   ${port.admin_up ? 'no shutdown' : 'shutdown'}`,
        `   switchport mode ${tagged.length ? 'trunk' : 'access'}`,
        tagged.length
          ? `   switchport trunk native vlan ${v}`
          : `   switchport access vlan ${v}`,
        tagged.length ? `   switchport trunk allowed vlan ${[v, ...tagged].join(',')}` : null,
      ]
        .filter(Boolean)
        .join('\n');
    case 'pica8':
      return [
        `set interface ${port.name} description "${desc}"`,
        `set interface ${port.name} ${port.admin_up ? 'enable' : 'disable'}`,
        `set vlans v${v} interface ${port.name} untagged`,
        ...tagged.map((t) => `set vlans v${t} interface ${port.name} tagged`),
      ].join('\n');
    case 'freebsd':
      return [
        `# /etc/rc.conf snippet`,
        `ifconfig_${port.name}="up"`,
        `# vlans on ${port.name}: ${[v, ...tagged].join(',')}`,
        `ifconfig_${port.name}_${v}="inet 10.0.${v}.1/24"`,
      ].join('\n');
    case 'mikrotik':
      return [
        `/interface set [find name=${port.name}] comment="${desc}"`,
        `/interface ${port.admin_up ? 'enable' : 'disable'} [find name=${port.name}]`,
        tagged.length
          ? `# trunk: configure /interface bridge vlan tagged=${port.name} vlan-ids=${tagged.join(',')}`
          : `/interface bridge port set [find interface=${port.name}] pvid=${v}`,
      ]
        .filter(Boolean)
        .join('\n');
  }
}

export function renderFullConfig(device: Device, ports: Port[]): string[] {
  switch (device.platform) {
    case 'cisco':
      return renderIos(device, ports, 'IOS-XE / NX-OS');
    case 'arista':
      return renderIos(device, ports, 'EOS');
    case 'pica8':
      return renderPica8(device, ports);
    case 'mikrotik':
      return renderMikrotik(device, ports);
    case 'freebsd':
      return renderFreeBSD(device, ports);
    case 'mock':
      return [`# mock driver · ${device.model}`, `hostname ${device.name}`];
  }
}

function renderMikrotik(device: Device, ports: Port[]): string[] {
  const lines: string[] = [
    `# RouterOS · ${device.model}`,
    `/system identity set name=${device.name}`,
  ];
  for (const p of ports) {
    lines.push(`/interface set [find name=${p.name}] ${p.admin_up ? 'disabled=no' : 'disabled=yes'}`);
    if (p.description) lines.push(`/interface set [find name=${p.name}] comment="${p.description}"`);
    if (p.tagged_vlans.length === 0) {
      lines.push(`/interface bridge port set [find interface=${p.name}] pvid=${p.untagged_vlan}`);
    }
  }
  return lines;
}

function renderIos(device: Device, ports: Port[], os: string): string[] {
  const lines: string[] = [`! ${os} · ${device.model}`, `hostname ${device.name}`, `!`];
  const vlans = new Set<number>();
  for (const p of ports) {
    vlans.add(p.untagged_vlan);
    p.tagged_vlans.forEach((v) => vlans.add(v));
  }
  for (const v of [...vlans].sort((a, b) => a - b)) {
    lines.push(`vlan ${v}`, `   name VLAN_${v}`, `!`);
  }
  for (const p of ports) {
    lines.push(`interface ${p.name}`);
    if (p.description) lines.push(`   description ${p.description}`);
    lines.push(`   ${p.admin_up ? 'no shutdown' : 'shutdown'}`);
    if (p.tagged_vlans.length) {
      lines.push(
        `   switchport mode trunk`,
        `   switchport trunk native vlan ${p.untagged_vlan}`,
        `   switchport trunk allowed vlan ${[p.untagged_vlan, ...p.tagged_vlans].join(',')}`,
      );
    } else {
      lines.push(`   switchport mode access`, `   switchport access vlan ${p.untagged_vlan}`);
    }
    lines.push(`!`);
  }
  return lines;
}

function renderPica8(device: Device, ports: Port[]): string[] {
  const lines: string[] = [`# PicOS · ${device.model}`, `set system hostname ${device.name}`, ``];
  const vlans = new Set<number>();
  for (const p of ports) {
    vlans.add(p.untagged_vlan);
    p.tagged_vlans.forEach((v) => vlans.add(v));
  }
  for (const v of [...vlans].sort((a, b) => a - b)) {
    lines.push(`set vlans v${v} description "VLAN ${v}"`);
  }
  lines.push(``);
  for (const p of ports) {
    lines.push(`set interface ${p.name} description "${p.description}"`);
    lines.push(`set interface ${p.name} ${p.admin_up ? 'enable' : 'disable'}`);
    lines.push(`set vlans v${p.untagged_vlan} interface ${p.name} untagged`);
    for (const t of p.tagged_vlans) lines.push(`set vlans v${t} interface ${p.name} tagged`);
  }
  return lines;
}

function renderFreeBSD(device: Device, ports: Port[]): string[] {
  const lines: string[] = [
    `# /etc/rc.conf`,
    `hostname="${device.name}"`,
    `gateway_enable="YES"`,
    `# interfaces`,
  ];
  for (const p of ports) lines.push(`ifconfig_${p.name}="${p.admin_up ? 'up' : 'down'}"`);
  lines.push(`# vlans`);
  for (const p of ports) {
    for (const v of [p.untagged_vlan, ...p.tagged_vlans]) {
      lines.push(`ifconfig_${p.name}_${v}="inet 10.0.${v}.1/24"`);
    }
  }
  lines.push(
    ``,
    `# /usr/local/etc/frr/frr.conf (excerpt)`,
    `frr defaults traditional`,
    `router bgp 65001`,
    `   bgp router-id 10.20.0.1`,
  );
  return lines;
}
