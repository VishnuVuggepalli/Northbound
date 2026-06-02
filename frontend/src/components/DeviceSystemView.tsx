import { useMemo, useState } from 'react';
import { Loader2, Network, ShieldCheck, Table2 } from 'lucide-react';
import { useSystemInfo } from '@/api/queries';
import { Section } from '@/components/ui/Section';
import { KV } from '@/components/ui/KV';
import { StatusDot } from '@/components/ui/StatusDot';
import { Input } from '@/components/ui/Input';
import type { Device } from '@/types';

function SectionTitle({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-2">
      {icon}
      {children}
    </span>
  );
}

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
    <div className="h-full overflow-auto nb-scroll px-4">
      <Section title={<SectionTitle icon={<Network size={13} className="text-accent" />}>Control-plane protocols</SectionTitle>}>
        {data.protocols.length === 0 ? (
          <p className="px-1 text-xs text-fg-subtle">None configured.</p>
        ) : (
          <ul className="space-y-2.5 px-1">
            {data.protocols.map((p) => (
              <li key={p.name} className="text-sm">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-fg">
                    <StatusDot state={p.enabled ? 'up' : 'off'} size={6} />
                    {p.name}
                  </span>
                  <span className="nb-mono text-xs text-fg-subtle">
                    {p.enabled ? p.detail : 'disabled'}
                  </span>
                </div>
                {p.enabled && p.params.length > 0 && (
                  <dl className="ml-4 mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                    {p.params.map(([k, v]) => (
                      <KV key={k} label={k}>
                        <span className="nb-mono text-fg-muted">{v}</span>
                      </KV>
                    ))}
                  </dl>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={<SectionTitle icon={<ShieldCheck size={13} className="text-accent" />}>Management services</SectionTitle>}>
        {data.services.length === 0 ? (
          <p className="px-1 text-xs text-fg-subtle">None reported.</p>
        ) : (
          <ul className="space-y-1.5 px-1">
            {data.services.map((s) => (
              <li
                key={s.name}
                className={
                  'flex items-center justify-between text-sm ' +
                  (s.configured ? '' : 'opacity-50')
                }
              >
                <span className="flex items-center gap-2 text-fg">
                  <StatusDot state={s.configured ? (s.enabled ? 'up' : 'off') : 'disabled'} size={6} />
                  {s.name}
                </span>
                <span className="nb-mono text-xs text-fg-subtle">
                  {s.configured ? (s.port != null ? `:${s.port}` : '') : 'not configured'}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title={
          <SectionTitle icon={<Table2 size={13} className="text-accent" />}>
            MAC address table
            <span className="nb-mono ml-1 text-xs text-fg-subtle">
              {data.mac_supported ? `${data.mac_table.length} entries` : 'not available'}
            </span>
          </SectionTitle>
        }
        right={
          data.mac_supported && data.mac_table.length > 0 ? (
            <Input
              placeholder="Filter by MAC / VLAN / interface…"
              value={macFilter}
              onChange={(e) => setMacFilter(e.target.value)}
              className="h-8 w-64 text-xs"
            />
          ) : undefined
        }
      >
        {!data.mac_supported ? (
          <p className="px-1 text-xs text-fg-subtle">
            This device&apos;s management API does not expose the forwarding table.
          </p>
        ) : macRows.length === 0 ? (
          <p className="px-1 text-xs text-fg-subtle">No matching entries.</p>
        ) : (
          <div className="overflow-x-auto px-1">
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
      </Section>
    </div>
  );
}
