/**
 * Color palette presets.
 *
 * Each palette overrides a small set of root CSS variables — `--nb-accent`,
 * `--nb-link`, and the background hue/chroma. Switching is a CSS-only
 * operation; no React tree re-mounts.
 */

export type PaletteId = 'noc' | 'blueprint' | 'phosphor';
export type ThemeMode = 'dark' | 'light';

interface ColorPair {
  dark: string;
  light: string;
}

export interface Palette {
  id: PaletteId;
  label: string;
  accent: ColorPair;
  accentFg: ColorPair;
  link: ColorPair;
  bgHue: number;
  bgChroma: number;
}

export const PALETTES: Readonly<Record<PaletteId, Palette>> = {
  noc: {
    id: 'noc',
    label: 'NOC Cyan',
    accent: { dark: 'oklch(0.80 0.13 220)', light: 'oklch(0.55 0.13 220)' },
    accentFg: { dark: 'oklch(0.14 0.04 220)', light: 'oklch(0.99 0.01 220)' },
    link: { dark: 'oklch(0.82 0.21 145)', light: 'oklch(0.55 0.18 145)' },
    bgHue: 232,
    bgChroma: 0.018,
  },
  blueprint: {
    id: 'blueprint',
    label: 'Blueprint Amber',
    accent: { dark: 'oklch(0.82 0.14 75)', light: 'oklch(0.55 0.14 70)' },
    accentFg: { dark: 'oklch(0.16 0.04 70)', light: 'oklch(0.99 0.01 70)' },
    link: { dark: 'oklch(0.82 0.21 145)', light: 'oklch(0.50 0.18 145)' },
    bgHue: 220,
    bgChroma: 0.012,
  },
  phosphor: {
    id: 'phosphor',
    label: 'Phosphor Tri-tone',
    accent: { dark: 'oklch(0.82 0.18 195)', light: 'oklch(0.50 0.15 195)' },
    accentFg: { dark: 'oklch(0.10 0.04 195)', light: 'oklch(0.99 0.01 195)' },
    link: { dark: 'oklch(0.86 0.24 140)', light: 'oklch(0.50 0.20 140)' },
    bgHue: 210,
    bgChroma: 0.008,
  },
};

export function applyPalette(palette: Palette, theme: ThemeMode): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.dataset.palette = palette.id;
  root.style.setProperty('--nb-bg-hue', String(palette.bgHue));
  root.style.setProperty('--nb-bg-chroma', String(palette.bgChroma));
  root.style.setProperty('--nb-accent', palette.accent[theme]);
  root.style.setProperty('--nb-accent-fg', palette.accentFg[theme]);
  // soft variants — same color with reduced alpha for chips and glows
  root.style.setProperty('--nb-accent-soft', palette.accent[theme].replace(/\)$/, ' / 0.18)'));
  root.style.setProperty('--nb-link', palette.link[theme]);
  root.style.setProperty('--nb-link-soft', palette.link[theme].replace(/\)$/, ' / 0.18)'));
}
