import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { PortCage } from './PortCage';
import type { CageBox } from './geometry';
import type { Port } from '@/models';

function port(over: Partial<Port> = {}): Port {
  return {
    device_id: 'd1', name: 'xe-1/1/1', index: 1, state: 'up', admin_up: true, link_up: true,
    speed_mbps: 10000, duplex: 'full', mac: null, mtu: 9216, untagged_vlan: 1010,
    tagged_vlans: [], description: '', host_model: '', bmc_ip: '', notes: '',
    services: {}, rx_bytes: null, tx_bytes: null, traffic: 0, last_change: 0,
    ...over,
  } as Port;
}

function cage(ports: Port[], over: Partial<CageBox> = {}): CageBox {
  return {
    x: 0, y: 0, w: 30, h: 26,
    id: ports[0]?.name ?? 'x', index: 1, ports,
    connector: 'rj45', groupIndex: 0,
    ...over,
  };
}

function draw(c: CageBox) {
  return render(
    <svg>
      <PortCage cage={c} selected={false} pending={false} vlanColor="#0af" onSelect={() => {}} />
    </svg>,
  ).container;
}

describe('PortCage — trunk vs access', () => {
  it('marks a trunk with a tagged count', () => {
    const c = draw(cage([port({ tagged_vlans: [100, 200, 300] })]));
    expect(c.textContent).toContain('+3');
  });

  it('shows no tagged count on an access port', () => {
    const c = draw(cage([port({ tagged_vlans: [] })]));
    expect(c.textContent).not.toContain('+');
  });

  it('draws a SECOND stripe for a trunk so the shape differs, not just the text', () => {
    // The whole point of 4b: a trunk must be distinguishable across a bank
    // without reading 6px type.
    const access = draw(cage([port({ tagged_vlans: [] })]));
    const trunk = draw(cage([port({ tagged_vlans: [100] })]));
    const stripes = (el: Element) => el.querySelectorAll('rect[fill="#0af"]').length;
    expect(stripes(trunk)).toBe(stripes(access) + 1);
  });

  it('draws no stripes at all on a down port', () => {
    // Stripes are identity, but a down port has no live identity to assert.
    const c = draw(cage([port({ state: 'down', tagged_vlans: [100] })]));
    expect(c.querySelectorAll('rect[fill="#0af"]')).toHaveLength(0);
  });

  it('singularises a one-tag trunk', () => {
    const c = draw(cage([port({ tagged_vlans: [100] })]));
    const label = c.querySelector('[role="button"]')!.getAttribute('aria-label')!;
    expect(label).toContain('1 tagged VLAN');
    expect(label).not.toContain('1 tagged VLANs');
  });

  it('names trunk state and tag count in the accessible label', () => {
    const c = draw(cage([port({ name: 'xe-1/1/5', tagged_vlans: [1, 2] })]));
    const label = c.querySelector('[role="button"]')!.getAttribute('aria-label')!;
    expect(label).toContain('xe-1/1/5');
    expect(label).toContain('trunk');
    expect(label).toContain('2 tagged VLANs');
  });

  it('says access in the label when there are no tags', () => {
    const c = draw(cage([port({ tagged_vlans: [] })]));
    expect(c.querySelector('[role="button"]')!.getAttribute('aria-label')).toContain('access');
  });

  it('stacks the breakout multiplier below the tag count instead of overlapping it', () => {
    const ports = [
      port({ name: 'xe-1/1/2:1', tagged_vlans: [10, 20] }),
      port({ name: 'xe-1/1/2:2', tagged_vlans: [10, 20] }),
    ];
    const c = draw(cage(ports, { id: 'xe-1/1/2' }));
    const texts = [...c.querySelectorAll('text')];
    expect(texts.map((t) => t.textContent)).toEqual(['+2', '×2']);
    // Different y, or they would render on top of one another.
    const ys = texts.map((t) => Number(t.getAttribute('y')));
    expect(ys[0]).not.toBe(ys[1]);
  });

  it('reports breakout lanes in the label', () => {
    const ports = [port({ name: 'a:1' }), port({ name: 'a:2' })];
    const c = draw(cage(ports, { id: 'a' }));
    expect(c.querySelector('[role="button"]')!.getAttribute('aria-label')).toContain(
      '2 breakout lanes',
    );
  });
});
