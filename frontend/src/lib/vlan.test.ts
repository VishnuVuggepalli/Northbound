import { describe, expect, it } from 'vitest';
import { vlanColor, vlanHue, vlanRGB, vlanZone } from './vlan';

describe('vlan colors', () => {
  it('returns the curated zone for canonical VLANs', () => {
    expect(vlanZone(10)?.name).toBe('mgmt');
    expect(vlanZone(100)?.name).toBe('prod');
    expect(vlanZone(999)?.name).toBe('guest');
  });

  it('produces deterministic hue for unknown VLANs', () => {
    const a = vlanHue(4242);
    const b = vlanHue(4242);
    expect(a).toBe(b);
    expect(a).toBeGreaterThanOrEqual(0);
    expect(a).toBeLessThan(360);
  });

  it('vlanColor returns an oklch string', () => {
    expect(vlanColor(100, 'dark')).toMatch(/oklch\(/);
  });

  it('vlanColor uses different lightness in light theme', () => {
    expect(vlanColor(100, 'dark')).not.toBe(vlanColor(100, 'light'));
  });

  it('vlanRGB returns a 0..1 triple', () => {
    const [r, g, b] = vlanRGB(100);
    for (const v of [r, g, b]) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
    }
  });

  it('vlanColor handles null gracefully', () => {
    expect(vlanColor(null, 'dark')).toMatch(/oklch\(/);
  });
});
