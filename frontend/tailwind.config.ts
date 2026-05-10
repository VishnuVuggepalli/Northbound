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
        sans: ['"Inter Tight"', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
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
      },
      animation: {
        'pulse-soft': 'pulse-soft 1s ease-in-out infinite',
        'fade-in': 'fade-in 160ms ease-out',
        'slide-in-right': 'slide-in-right 200ms ease-out',
      },
    },
  },
  plugins: [],
};

export default config;
