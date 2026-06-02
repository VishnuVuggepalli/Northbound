import { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Loader2, Network, ShieldCheck, Table2 } from 'lucide-react';
import { useProtocolDetail, useSystemInfo } from '@/api/queries';
import { Section } from '@/components/ui/Section';
import { KV } from '@/components/ui/KV';
import { DataTable } from '@/components/ui/DataTable';
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
    <div className="h-full overflow-auto nb-scroll px-4 pb-16">
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
                {p.has_detail && <ProtocolGets deviceId={device.id} slug={p.name} />}
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
          <div className="px-1">
            <DataTable
              columns={['VLAN', 'MAC address', 'Type', 'Age', 'Interface']}
              rows={macRows.map((r) => [
                String(r.vlan ?? '—'),
                r.mac,
                r.type,
                r.age ?? '—',
                r.interface,
              ])}
              cellClass={(j) => (j === 4 ? 'text-link' : j === 1 ? 'text-fg' : 'text-fg-muted')}
            />
          </div>
        )}
      </Section>
    </div>
  );
}

/** Lazy-loaded operational tables for a protocol (OSPF neighbors, etc.). */
function ProtocolGets({ deviceId, slug }: { deviceId: string; slug: string }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading, isError } = useProtocolDetail(deviceId, slug, open);
  return (
    <div className="ml-4 mt-1.5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-xs text-accent hover:underline"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        Operational detail
      </button>
      {open && (
        <div className="mt-2 space-y-3">
          {isLoading && (
            <div className="flex items-center gap-2 text-xs text-fg-muted">
              <Loader2 className="animate-spin" size={12} /> Reading from device…
            </div>
          )}
          {isError && <p className="text-xs text-danger">Failed to read operational state.</p>}
          {data?.error && <p className="text-xs text-warn">{data.error}</p>}
          {data?.tables.map((t) => (
            <div key={t.title}>
              <div className="mb-1 text-[10px] uppercase tracking-wider text-fg-subtle">
                {t.title} · {t.rows.length}
              </div>
              {t.rows.length === 0 ? (
                <p className="text-xs text-fg-subtle">No entries.</p>
              ) : (
                <DataTable columns={t.columns} rows={t.rows} />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
