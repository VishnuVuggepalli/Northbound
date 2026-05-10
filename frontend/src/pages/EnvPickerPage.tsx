import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Topology3D } from '@/components/three/Topology3D';
import { Wordmark } from '@/components/ui/Wordmark';
import { useAuthStore } from '@/store/auth';
import { useThemeStore } from '@/store/theme';
import { useUIStore } from '@/store/ui';
import { useAllPorts, useDevices, useLinks, useRequests } from '@/api/queries';
import { timeAgo } from '@/lib/format';
import type { Environment } from '@/types';

export function EnvPickerPage() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const theme = useThemeStore((s) => s.theme);
  const setEnv = useUIStore((s) => s.setEnv);
  const { data: devices = [] } = useDevices();
  const { data: ports = {} } = useAllPorts();
  const { data: links = [] } = useLinks();
  const { data: requests = [] } = useRequests();

  const envs = useMemo<Environment[]>(() => ['lab', 'dc'], []);

  const stats = useMemo(() => {
    const out: Record<Environment, {
      devices: number;
      ports: number;
      up: number;
      pending: number;
      updated: number;
    }> = {
      lab: { devices: 0, ports: 0, up: 0, pending: 0, updated: 0 },
      dc: { devices: 0, ports: 0, up: 0, pending: 0, updated: 0 },
    };
    for (const env of envs) {
      const ds = devices.filter((d) => d.env === env);
      const ps = ds.flatMap((d) => ports[d.id] ?? []);
      const rq = requests.filter(
        (r) => ds.some((d) => d.id === r.device_id) && r.status === 'pending',
      );
      out[env] = {
        devices: ds.length,
        ports: ps.length,
        up: ps.filter((p) => p.state === 'up').length,
        pending: rq.length,
        updated: Date.now() - 1000 * 60 * 2,
      };
    }
    return out;
  }, [devices, ports, requests, envs]);

  const handlePick = (env: Environment) => {
    setEnv(env);
    navigate(`/env/${env}`);
  };

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] flex-col">
      <div className="border-b border-border bg-bg-elev-1/40 px-6 py-8">
        <div className="mx-auto max-w-5xl">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-fg-subtle">
            <Wordmark size={14} glyph={false} />
            <span>·</span>
            <span>v0.1 · internal</span>
          </div>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-fg text-balance">
            Pick an environment
          </h1>
          <p className="mt-1 max-w-xl text-sm text-fg-muted">
            Live state, structured requests, no more port-by-DM.
          </p>
        </div>
      </div>

      <div className="flex-1 px-6 py-8">
        <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-2">
          {envs.map((env) => {
            const ds = devices.filter((d) => d.env === env);
            const envLinks = links.filter(
              ([a]) => devices.find((d) => d.id === a)?.env === env,
            );
            const s = stats[env];
            return (
              <button
                key={env}
                type="button"
                onClick={() => handlePick(env)}
                className="group flex flex-col overflow-hidden rounded-2xl border border-border bg-bg-elev-1 text-left transition-all hover:-translate-y-0.5 hover:border-accent/60 hover:shadow-[0_8px_40px_-8px_var(--nb-accent-soft)]"
              >
                <div className="aspect-[4/2.4] w-full">
                  <Topology3D devices={ds} links={envLinks} theme={theme} ambient />
                </div>
                <div className="border-t border-border p-5">
                  <div className="flex items-baseline justify-between">
                    <h2 className="text-xl font-semibold text-fg">
                      {env === 'lab' ? 'Lab' : 'Datacenter'}
                    </h2>
                    <span className="text-xs text-fg-subtle">updated {timeAgo(s.updated)}</span>
                  </div>
                  <dl className="mt-4 grid grid-cols-4 gap-3">
                    <Stat label="devices" value={s.devices} />
                    <Stat label="ports" value={s.ports} />
                    <Stat label="up" value={s.up} tone="success" />
                    <Stat label="pending" value={s.pending} tone={s.pending ? 'warn' : undefined} />
                  </dl>
                  <div className="mt-5 flex items-center justify-end gap-1.5 text-sm font-medium text-accent group-hover:translate-x-0.5 transition-transform">
                    <span>Enter</span>
                    <ArrowRight size={14} />
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        <div className="mx-auto mt-10 flex max-w-5xl items-center justify-between text-xs text-fg-subtle">
          <span>
            Connected as <strong className="text-fg-muted">{user?.name ?? 'guest'}</strong>
          </span>
          <span className="nb-mono">tailnet · northbound.lab</span>
        </div>

        <div className="mx-auto mt-6 max-w-5xl">
          <Link
            to="/onboard"
            className="inline-flex items-center gap-2 rounded-md border border-dashed border-border px-3 py-1.5 text-xs text-fg-muted hover:border-accent hover:text-accent"
          >
            + Onboard a new device
          </Link>
        </div>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: 'success' | 'warn';
}) {
  const TONE: Record<NonNullable<typeof tone> | 'default', string> = {
    default: 'text-fg',
    success: 'text-success',
    warn: 'text-warn',
  };
  // Each stat is a <div> wrapper holding a <dt>/<dd> pair so the surrounding
  // <dl> is structurally valid (axe `definition-list`). Visually we want value
  // on top, label below — flex-col-reverse achieves that without changing DOM
  // order.
  return (
    <div className="flex flex-col-reverse">
      <dt className="text-[10px] uppercase tracking-wider text-fg-subtle">{label}</dt>
      <dd className={`mb-0.5 text-2xl font-semibold ${tone ? TONE[tone] : TONE.default}`}>
        {value}
      </dd>
    </div>
  );
}
