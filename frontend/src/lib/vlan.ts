/**
 * VLAN colors — deterministic, palette-stable.
 *
 * Same VLAN number must produce the same hue everywhere it appears
 * (3D LED, 2D port card, request form, diff view). Curated zones for the
 * canonical VLANs (mgmt 10 / storage 20 / prod 100 / voip 200 / transit 300 /
 * guest 999) keep the visual identity consistent; everything else falls back
 * to a stable hash.
 *
 * Ports from `theme.jsx` in the prototype, expanded for use in TypeScript
 * with explicit return types.
 */

export interface VlanZone {
  name: string;
  hue: number;
}

const VLAN_ZONES: Readonly<Record<number, VlanZone>> = {
  10: { name: 'mgmt', hue: 220 },
  20: { name: 'storage', hue: 280 },
  50: { name: 'dmz', hue: 25 },
  100: { name: 'prod', hue: 145 },
  150: { name: 'ipmi', hue: 250 },
  200: { name: 'voip', hue: 35 },
  300: { name: 'transit', hue: 320 },
  999: { name: 'guest', hue: 75 },
};

/** FNV-1a 32-bit hash, identical to the prototype implementation. */
function hashInt(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function vlanZone(vlan: number | null | undefined): VlanZone | null {
  if (vlan == null) return null;
  return VLAN_ZONES[vlan] ?? null;
}

export function vlanHue(vlan: number | null | undefined): number {
  if (vlan == null) return 240;
  const zone = vlanZone(vlan);
  if (zone) return zone.hue;
  return hashInt(`vlan-${vlan}`) % 360;
}

export type ThemeMode = 'dark' | 'light';

export function vlanColor(vlan: number | null | undefined, theme: ThemeMode = 'dark'): string {
  if (vlan == null) {
    return theme === 'dark' ? 'oklch(0.7 0.01 240)' : 'oklch(0.5 0.01 240)';
  }
  const h = vlanHue(vlan);
  // Lightness raised so VLAN-tinted text passes 4.5:1 against bg-elev-1
  // (L≈0.22). At L=0.74 (the original) hue=25/35 measured 3.9; at L=0.84
  // hue=35 still measured ~4.4 due to oklch→sRGB compression. L=0.88 with
  // chroma capped at 0.12 keeps every canonical zone above the floor while
  // still reading as the brand color.
  const L = theme === 'dark' ? 0.88 : 0.42;
  const C = theme === 'dark' ? 0.12 : 0.16;
  return `oklch(${L} ${C} ${h})`;
}

export function vlanColorMuted(
  vlan: number | null | undefined,
  theme: ThemeMode = 'dark',
): string {
  if (vlan == null) {
    return theme === 'dark' ? 'oklch(0.30 0.01 240 / 0.6)' : 'oklch(0.85 0.01 240 / 0.7)';
  }
  const h = vlanHue(vlan);
  const L = theme === 'dark' ? 0.3 : 0.92;
  const C = theme === 'dark' ? 0.07 : 0.05;
  return `oklch(${L} ${C} ${h})`;
}

/**
 * RGB triplet in 0..1 — used by three.js materials, which need linear RGB,
 * not CSS oklch. Approximates the same hue via HSL with fixed S/L tuned to
 * read well on emissive materials.
 */
export function vlanRGB(vlan: number | null | undefined): [number, number, number] {
  const hue = vlanHue(vlan) / 360;
  const s = 0.7;
  const l = 0.6;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => {
    const k = (n + hue * 12) % 12;
    return l - a * Math.max(-1, Math.min(Math.min(k - 3, 9 - k), 1));
  };
  return [f(0), f(8), f(4)];
}
