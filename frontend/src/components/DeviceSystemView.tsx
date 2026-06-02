import { useMemo, useState } from 'react';
import { Loader2, Network, ShieldCheck, Table2 } from 'lucide-react';
import { useSystemInfo } from '@/api/queries';
import { StatusDot } from '@/components/ui/StatusDot';
import { Input } from '@/components/ui/Input';
import type { Device } from '@/types';

interface DeviceSystemViewProps {
  device: Device;
}

/** Live system tab: control-plane protocols, mgmt services, L2 MAC table. */
export function DeviceSystemView({ device }: DeviceSystemViewProps) {
  const { data, isLoading, isError, error } = useSystemInfo(device.id);
  const [macFilter, setMacFilter] = useState('');

  const macRows = useMemo(() => {
    const rows = data?.mac_table ?? [];
    const q = macFilter.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.mac.toLowerCase().includes(q) ||
        r.interface.toLowerCase().includes(q) ||
        String(r.vlan ?? '').includes(q),
    );
  }, [data?.mac_table, macFilter]);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-fg-muted">
        <Loader2 className="animate-spin" size={16} /> Reading live system state…
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1 text-center text-fg-muted">
        <div className="text-base font-semibold text-fg">Could not read system info</div>
        <div className="text-sm">{error instanceof Error ? error.message : 'Device unreachable.'}</div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto nb-scroll p-4">
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Protocols */}
        <section className="rounded-lg border border-border bg-bg-elev-1/40 p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-fg">
            <Network size={14} className="text-accent" /> Control-plane protocols
          </h3>
          {data.protocols.length === 0 ? (
            <p className="text-xs text-fg-subtle">None configured.</p>
          ) : (
            <ul className="space-y-1.5">
              {data.protocols.map((p) => (
                <li key={p.name} className="flex items-center justify-between text-sm">
                  <span className="flex items-center gap-2 text-fg">
                    <StatusDot state={p.enabled ? 'up' : 'off'} size={6} />
                    {p.name}
                  </span>
                  {p.detail && <span className="nb-mono text-xs text-fg-subtle">{p.detail}</span>}
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Mgmt services */}
        <section className="rounded-lg border border-border bg-bg-elev-1/40 p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-fg">
            <ShieldCheck size={14} className="text-accent" /> Management services
          </h3>
          {data.services.length === 0 ? (
            <p className="text-xs text-fg-subtle">None reported.</p>
          ) : (
            <ul className="space-y-1.5">
              {data.services.map((s) => (
                <li key={s.name} className="flex items-center justify-between text-sm">
                  <span className="flex items-center gap-2 text-fg">
                    <StatusDot state={s.enabled ? 'up' : 'off'} size={6} />
                    {s.name}
                  </span>
                  {s.port != null && (
                    <span className="nb-mono text-xs text-fg-subtle">:{s.port}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* MAC table */}
      <section className="mt-4 rounded-lg border border-border bg-bg-elev-1/40 p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-fg">
            <Table2 size={14} className="text-accent" /> MAC address table
            <span className="nb-mono text-xs text-fg-subtle">
              {data.mac_supported ? `${data.mac_table.length} entries` : 'not available'}
            </span>
          </h3>
          {data.mac_supported && data.mac_table.length > 0 && (
            <Input
              placeholder="Filter by MAC / VLAN / interface…"
              value={macFilter}
              onChange={(e) => setMacFilter(e.target.value)}
              className="h-8 w-64 text-xs"
            />
          )}
        </div>
        {!data.mac_supported ? (
          <p className="text-xs text-fg-subtle">
            This device&apos;s management API does not expose the forwarding table.
          </p>
        ) : macRows.length === 0 ? (
          <p className="text-xs text-fg-subtle">No matching entries.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-xs">
              <thead>
                <tr className="border-b border-border text-fg-subtle">
                  <th className="py-1.5 pr-4 font-medium">VLAN</th>
                  <th className="py-1.5 pr-4 font-medium">MAC address</th>
                  <th className="py-1.5 pr-4 font-medium">Type</th>
                  <th className="py-1.5 pr-4 font-medium">Age</th>
                  <th className="py-1.5 font-medium">Interface</th>
                </tr>
              </thead>
              <tbody className="nb-mono">
                {macRows.map((r, i) => (
                  <tr key={`${r.mac}-${r.interface}-${i}`} className="border-b border-border/40">
                    <td className="py-1 pr-4 text-fg-muted">{r.vlan ?? '—'}</td>
                    <td className="py-1 pr-4 text-fg">{r.mac}</td>
                    <td className="py-1 pr-4 text-fg-muted">{r.type}</td>
                    <td className="py-1 pr-4 text-fg-subtle">{r.age ?? '—'}</td>
                    <td className="py-1 text-link">{r.interface}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
