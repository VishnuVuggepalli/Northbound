/**
 * Theme store — dark/light + palette.
 *
 * `applyPalette` writes CSS variables on `document.documentElement` so the
 * whole tree picks up the change without a re-render.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { PALETTES, type PaletteId, type ThemeMode, applyPalette } from '@/lib/palette';

interface ThemeState {
  theme: ThemeMode;
  palette: PaletteId;
  setTheme: (t: ThemeMode) => void;
  setPalette: (p: PaletteId) => void;
  toggle: () => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: 'dark',
      palette: 'noc',
      setTheme: (theme) => {
        set({ theme });
        applyPalette(PALETTES[get().palette], theme);
      },
      setPalette: (palette) => {
        set({ palette });
        applyPalette(PALETTES[palette], get().theme);
      },
      toggle: () => {
        const next: ThemeMode = get().theme === 'dark' ? 'light' : 'dark';
        set({ theme: next });
        applyPalette(PALETTES[get().palette], next);
      },
    }),
    {
      name: 'nb-theme',
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        applyPalette(PALETTES[state.palette], state.theme);
      },
    },
  ),
);
