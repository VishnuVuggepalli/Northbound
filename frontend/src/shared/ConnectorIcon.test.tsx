import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { ConnectorIcon } from './ConnectorIcon';
import { CONNECTOR_LABEL, type ConnectorType } from '@/lib/faceplate';

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
    const { container } = render(<ConnectorIcon kind="rj45" />);
    expect(container.querySelectorAll('line')).toHaveLength(8);
    // The silhouette must step DOWN below the opening and back up — that step
    // is the latch keyway.
    const d = container.querySelector('path')!.getAttribute('d')!;
    expect(d).toContain('V18');
    expect(d).toContain('h-6.5');
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
