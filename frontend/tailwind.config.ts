import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: ['class', '[data-theme="dark"]'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    container: {
      center: true,
      padding: '1rem',
    },
    extend: {
      colors: {
        // Surface tokens are oklch-based so the palette switcher can swap hue/chroma.
        bg: 'var(--nb-bg)',
        'bg-elev-1': 'var(--nb-bg-elev-1)',
        'bg-elev-2': 'var(--nb-bg-elev-2)',
        'bg-sunken': 'var(--nb-bg-sunken)',
        border: 'var(--nb-border)',
        'border-strong': 'var(--nb-border-strong)',
        fg: 'var(--nb-fg)',
        'fg-muted': 'var(--nb-fg-muted)',
        'fg-subtle': 'var(--nb-fg-subtle)',
        accent: 'var(--nb-accent)',
        'accent-fg': 'var(--nb-accent-fg)',
        'accent-soft': 'var(--nb-accent-soft)',
        link: 'var(--nb-link)',
        'link-soft': 'var(--nb-link-soft)',
        warn: 'var(--nb-warn)',
        'warn-soft': 'var(--nb-warn-soft)',
        danger: 'var(--nb-danger)',
        success: 'var(--nb-success)',
      },
      fontFamily: {
        // Sora — geometric display, used for headings, wordmark and UI body.
        sans: ['Sora', 'system-ui', 'sans-serif'],
        // IBM Plex Mono — the instrument typeface for data / ports / config.
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      letterSpacing: {
        tightest: '-0.03em',
      },
      keyframes: {
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.55' },
        },
        'fade-in': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-in-right': {
          '0%': { opacity: '0', transform: 'translateX(24px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        // Signature: page-load reveal — a measured rise + settle, staggered
        // via animation-delay (see .nb-reveal helpers in globals.css).
        'reveal-up': {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        // Signature: the compass needle swinging to true north on entry.
        'compass-lock': {
          '0%': { transform: 'rotate(-32deg)', opacity: '0.2' },
          '55%': { transform: 'rotate(6deg)' },
          '78%': { transform: 'rotate(-2deg)' },
          '100%': { transform: 'rotate(0deg)', opacity: '1' },
        },
        // Micro-interaction: confirm flash on apply / select.
        'tick-flash': {
          '0%': { boxShadow: '0 0 0 0 var(--nb-accent-soft)' },
          '100%': { boxShadow: '0 0 0 8px transparent' },
        },
      },
      animation: {
        'pulse-soft': 'pulse-soft 1s ease-in-out infinite',
        'fade-in': 'fade-in 160ms ease-out',
        'slide-in-right': 'slide-in-right 200ms ease-out',
        'reveal-up': 'reveal-up 440ms cubic-bezier(0.22, 1, 0.36, 1) both',
        'compass-lock': 'compass-lock 900ms cubic-bezier(0.34, 1.56, 0.64, 1) both',
        'tick-flash': 'tick-flash 360ms ease-out',
      },
    },
  },
  plugins: [],
};

export default config;
