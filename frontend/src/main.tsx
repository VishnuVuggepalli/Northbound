import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from './App';
import { applyPalette, PALETTES } from './lib/palette';
import { useThemeStore } from './store/theme';

// Self-hosted fonts (no CDN, offline-safe, no FOUT race in E2E).
// Sora — distinctive geometric display for headings + wordmark + UI body.
import '@fontsource/sora/latin-400.css';
import '@fontsource/sora/latin-500.css';
import '@fontsource/sora/latin-600.css';
import '@fontsource/sora/latin-700.css';
// IBM Plex Mono — the instrument typeface for ports / VLANs / config / data.
import '@fontsource/ibm-plex-mono/latin-400.css';
import '@fontsource/ibm-plex-mono/latin-500.css';
import '@fontsource/ibm-plex-mono/latin-600.css';
import './styles/globals.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

// Apply the persisted palette before first paint so we don't flash NOC defaults.
const initial = useThemeStore.getState();
applyPalette(PALETTES[initial.palette], initial.theme);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
