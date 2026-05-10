// Northbound — theme tokens, VLAN palette, color presets
const { createContext, useContext, useState, useEffect, useMemo } = React;

const ThemeContext = createContext(null);

// ---- Color presets (NOC-flavored) ------------------------------------
// Each preset defines: accent (chrome), link (always green-ish for "up"),
// warn (amber, disabled/pending), fault (red), info (cyan/blue).
const PALETTES = {
  noc: {
    label: 'NOC Cyan',
    accent: { dark: 'oklch(0.80 0.13 220)', light: 'oklch(0.55 0.13 220)' },
    accentFg: { dark: 'oklch(0.14 0.04 220)', light: 'oklch(0.99 0.01 220)' },
    link: { dark: 'oklch(0.82 0.21 145)', light: 'oklch(0.55 0.18 145)' },
    bgHue: 232, bgChroma: 0.018,
  },
  blueprint: {
    label: 'Blueprint Amber',
    accent: { dark: 'oklch(0.82 0.14 75)', light: 'oklch(0.55 0.14 70)' },
    accentFg: { dark: 'oklch(0.16 0.04 70)', light: 'oklch(0.99 0.01 70)' },
    link: { dark: 'oklch(0.82 0.21 145)', light: 'oklch(0.50 0.18 145)' },
    bgHue: 220, bgChroma: 0.012,
  },
  phosphor: {
    label: 'Phosphor Tri-tone',
    accent: { dark: 'oklch(0.82 0.18 195)', light: 'oklch(0.50 0.15 195)' },
    accentFg: { dark: 'oklch(0.10 0.04 195)', light: 'oklch(0.99 0.01 195)' },
    link: { dark: 'oklch(0.86 0.24 140)', light: 'oklch(0.50 0.20 140)' },
    bgHue: 210, bgChroma: 0.008,
  },
};

// Named VLAN zones (semantic). VLAN # → role → curated hue.
// Hand-picked hues at fixed chroma for cohesion with hash fallback.
const VLAN_ZONES = {
  10:  { name: 'mgmt',     hue: 220 }, // cyan-blue
  20:  { name: 'storage',  hue: 280 }, // violet
  100: { name: 'prod',     hue: 145 }, // green
  200: { name: 'voip',     hue: 35 },  // amber-orange
  300: { name: 'transit',  hue: 320 }, // magenta
  999: { name: 'guest',    hue: 75 },  // yellow-olive
  // common extras
  50:  { name: 'dmz',      hue: 25 },
  150: { name: 'ipmi',     hue: 250 },
};

function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => localStorage.getItem('nb_theme') || 'dark');
  const [palette, setPalette] = useState(() => localStorage.getItem('nb_palette') || 'noc');
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    root.dataset.palette = palette;
    const p = PALETTES[palette] || PALETTES.noc;
    const mode = theme;
    root.style.setProperty('--nb-accent', p.accent[mode]);
    root.style.setProperty('--nb-accent-fg', p.accentFg[mode]);
    root.style.setProperty('--nb-accent-soft', p.accent[mode].replace(/\)$/, ' / 0.18)'));
    root.style.setProperty('--nb-link', p.link[mode]);
    root.style.setProperty('--nb-link-soft', p.link[mode].replace(/\)$/, ' / 0.18)'));
    root.style.setProperty('--nb-bg-hue', String(p.bgHue));
    root.style.setProperty('--nb-bg-chroma', String(p.bgChroma));
    localStorage.setItem('nb_theme', theme);
    localStorage.setItem('nb_palette', palette);
  }, [theme, palette]);
  const value = useMemo(() => ({
    theme, setTheme, palette, setPalette,
    toggle: () => setTheme(t => t === 'dark' ? 'light' : 'dark'),
    palettes: PALETTES,
  }), [theme, palette]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
const useTheme = () => useContext(ThemeContext);

// Deterministic VLAN color
function hashInt(s) {
  let h = 2166136261 >>> 0;
  const str = String(s);
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
function vlanZone(vlan) { return VLAN_ZONES[vlan] || null; }
function vlanHue(vlan) {
  const z = vlanZone(vlan);
  if (z) return z.hue;
  return (hashInt('vlan-' + vlan) % 360);
}
function vlanColor(vlan, theme = 'dark') {
  if (vlan == null) return theme === 'dark' ? 'oklch(0.55 0.01 240)' : 'oklch(0.65 0.01 240)';
  const h = vlanHue(vlan);
  const L = theme === 'dark' ? 0.74 : 0.50;
  const C = 0.14;
  return `oklch(${L} ${C} ${h})`;
}
function vlanColorMuted(vlan, theme = 'dark') {
  if (vlan == null) return theme === 'dark' ? 'oklch(0.30 0.01 240 / 0.6)' : 'oklch(0.85 0.01 240 / 0.7)';
  const h = vlanHue(vlan);
  const L = theme === 'dark' ? 0.30 : 0.92;
  const C = theme === 'dark' ? 0.07 : 0.05;
  return `oklch(${L} ${C} ${h})`;
}
function vlanRGB(vlan) {
  const hue = vlanHue(vlan) / 360;
  const h = hue, s = 0.7, l = 0.6;
  const a = s * Math.min(l, 1 - l);
  const f = n => {
    const k = (n + h * 12) % 12;
    return l - a * Math.max(-1, Math.min(Math.min(k - 3, 9 - k), 1));
  };
  return [f(0), f(8), f(4)];
}

window.ThemeProvider = ThemeProvider;
window.useTheme = useTheme;
window.vlanColor = vlanColor;
window.vlanColorMuted = vlanColorMuted;
window.vlanHue = vlanHue;
window.vlanZone = vlanZone;
window.vlanRGB = vlanRGB;
window.PALETTES = PALETTES;
window.VLAN_ZONES = VLAN_ZONES;
