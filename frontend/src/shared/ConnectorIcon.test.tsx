import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { ConnectorIcon } from './ConnectorIcon';
import { CONNECTOR_LABEL, type ConnectorType } from '@/lib/faceplate';
import { RJ45_CONTACTS } from '@/lib/connectorShape';

const KINDS: ConnectorType[] = ['rj45', 'sfp', 'sfp28', 'qsfp', 'unknown'];

describe('ConnectorIcon', () => {
  it('renders every connector kind', () => {
    for (const kind of KINDS) {
      const { container } = render(<ConnectorIcon kind={kind} />);
      expect(container.querySelector('svg')).not.toBeNull();
    }
  });

  it('is hidden from assistive tech when decorative', () => {
    // Next to a visible port name the icon is noise, so it must not be read.
    const { container } = render(<ConnectorIcon kind="rj45" />);
    const svg = container.querySelector('svg')!;
    expect(svg.getAttribute('aria-hidden')).toBe('true');
    expect(svg.getAttribute('role')).toBeNull();
  });

  it('is exposed as an image when given a title', () => {
    const { container } = render(<ConnectorIcon kind="qsfp" title="QSFP port" />);
    const svg = container.querySelector('svg')!;
    expect(svg.getAttribute('role')).toBe('img');
    expect(svg.getAttribute('aria-label')).toBe('QSFP port');
    expect(svg.getAttribute('aria-hidden')).toBeNull();
  });

  it('draws the RJ45 keyway and all eight contacts', () => {
    // The keyway is what makes an RJ45 identifiable; the contacts are the
    // second cue. Losing either would leave a generic box.
    //
    // Asserted structurally, not against literal path text: the geometry now
    // comes from lib/connectorShape and is verified numerically there. This
    // test only guards that the glyph RENDERS what that module returns.
    const { container } = render(<ConnectorIcon kind="rj45" />);
    const contacts = container.querySelectorAll('rect[fill="currentColor"]');
    expect(contacts).toHaveLength(RJ45_CONTACTS);
    // The mouth is a single keyed silhouette — a path, not a plain rect.
    const d = container.querySelector('path')!.getAttribute('d')!;
    expect(d.startsWith('M')).toBe(true);
    // It must step down and back up: that step IS the latch keyway.
    const verticals = d.match(/v-?\d+(\.\d+)?/g) ?? [];
    expect(verticals.some((v) => v.startsWith('v-'))).toBe(true);
    expect(verticals.some((v) => !v.startsWith('v-'))).toBe(true);
  });

  it('gives QSFP a divider rib that SFP does not have', () => {
    const sfp = render(<ConnectorIcon kind="sfp" />).container.querySelectorAll('line');
    const qsfp = render(<ConnectorIcon kind="qsfp" />).container.querySelectorAll('line');
    expect(qsfp.length).toBeGreaterThan(sfp.length);
  });

  it('treats sfp28 as an SFP-family face', () => {
    const sfp = render(<ConnectorIcon kind="sfp" />).container.innerHTML;
    const sfp28 = render(<ConnectorIcon kind="sfp28" />).container.innerHTML;
    expect(sfp28).toBe(sfp);
  });

  it('honours the size prop', () => {
    const { container } = render(<ConnectorIcon kind="sfp" size={32} />);
    const svg = container.querySelector('svg')!;
    expect(svg.getAttribute('width')).toBe('32');
    expect(svg.getAttribute('height')).toBe('32');
  });

  it('inherits colour so it works in both themes', () => {
    const { container } = render(<ConnectorIcon kind="rj45" />);
    expect(container.querySelector('svg')!.getAttribute('stroke')).toBe('currentColor');
  });

  it('exposes a label for every kind', () => {
    for (const kind of KINDS) expect(CONNECTOR_LABEL[kind]).toBeTruthy();
  });
});
