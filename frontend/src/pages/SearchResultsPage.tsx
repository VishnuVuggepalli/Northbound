import { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { apiClient } from '@/api';
import { useUIStore } from '@/store/ui';
import { useThemeStore } from '@/store/theme';
import { VlanChip } from '@/components/ui/VlanChip';
import type { Device, Environment, Port } from '@/types';

export function SearchResultsPage() {
  const { env } = useParams<{ env: Environment }>();
  const [params] = useSearchParams();
  const q = params.get('q') ?? '';
  const navigate = useNavigate();
  const theme = useThemeStore((s) => s.theme);
  const selectPort = useUIStore((s) => s.selectPort);
  const [results, setResults] = useState<Array<{ device: Device; port: Port }>>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!env || (env !== 'lab' && env !== 'dc')) return;
    let cancelled = false;
    setError(null);
    void apiClient
      .searchPorts(env, q)
      .then((r) => {
        if (!cancelled) setResults(r);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // Don't swallow: log for diagnosis and tell the user the search failed
        // rather than showing a misleading empty result set.
        console.error(`searchPorts failed (env=${env}, q="${q}")`, err);
        setResults([]);
        setError(err instanceof Error ? err.message : 'Search failed');
      });
    return () => {
      cancelled = true;
    };
  }, [env, q]);

  if (env !== 'lab' && env !== 'dc') return null;

  return (
    <div className="mx-auto max-w-4xl px-6 py-6">
      <header className="mb-4">
        <div className="text-xs uppercase tracking-wider text-fg-subtle">Search · {env.toUpperCase()}</div>
        <h1 className="text-xl font-semibold text-fg">
          Results for <span className="nb-mono text-accent">{q}</span>
        </h1>
        <p className="mt-1 text-sm text-fg-muted">{results.length} match{results.length === 1 ? '' : 'es'}</p>
      </header>
      {error && (
        <div
          role="alert"
          className="mb-3 rounded-md border border-danger/50 bg-danger/10 px-3 py-2 text-sm text-danger"
        >
          Search failed: {error}
        </div>
      )}
      <div className="space-y-1.5">
        {results.map(({ device, port }) => (
          <button
            key={`${device.id}:${port.name}`}
            type="button"
            onClick={() => {
              selectPort(port.name);
              navigate(`/env/${env}/devices/${device.id}`);
            }}
            className="group grid w-full grid-cols-[160px_120px_minmax(0,1fr)_auto] items-center gap-3 rounded-md border border-border bg-bg-elev-1 px-3 py-2 text-left text-sm hover:border-accent/60"
          >
            <span className="nb-mono truncate text-fg">{device.name}</span>
            <span className="nb-mono truncate text-fg-muted">{port.name}</span>
            <span className="flex items-center gap-2">
              <VlanChip vlan={port.untagged_vlan} theme={theme} />
              <span className="truncate text-xs text-fg-muted">{port.description || '—'}</span>
            </span>
            <ArrowRight size={14} className="text-fg-subtle group-hover:text-accent" />
          </button>
        ))}
      </div>
    </div>
  );
}
