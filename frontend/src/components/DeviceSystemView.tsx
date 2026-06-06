import { useMemo, useState } from 'react';
import { Activity, ChevronDown, ChevronRight, Cpu, Layers, Loader2, Network, Router, ShieldCheck, Table2 } from 'lucide-react';
import {
  useCreateVlanRequest,
  useL3Interfaces,
  useProtocolDetail,
  useSystemInfo,
  useVlans,
} from '@/api/queries';
import { Section } from '@/shared/Section';
import { KV } from '@/shared/KV';
import { DataTable } from '@/shared/DataTable';
import { StatusDot } from '@/shared/StatusDot';
import { Input } from '@/shared/Input';
import { Button } from '@/shared/Button';
import { Plus } from 'lucide-react';
import { pushToast } from '@/store/toast';
import { cn } from '@/lib/cn';
import type { Device } from '@/models';

type SubTab = 'overview' | 'interfaces' | 'vlans' | 'mac' | 'diagnostics';

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

/** Live system tab: control-plane protocols, mgmt services, L2 MAC table, VLANs. */
export function DeviceSystemView({ device }: DeviceSystemViewProps) {
  const { data, isLoading, isError, error } = useSystemInfo(device.id);
  const { data: vlans = [] } = useVlans(device.id);
  const { data: l3 = [] } = useL3Interfaces(device.id);
  const [macFilter, setMacFilter] = useState('');
  const [vlanFilter, setVlanFilter] = useState('');
  const [sub, setSub] = useState<SubTab>('overview');
  const createVlan = useCreateVlanRequest();
  const [addingVlan, setAddingVlan] = useState(false);
  const [newVid, setNewVid] = useState('');
  const [newName, setNewName] = useState('');
  // A VLAN write must be filed as a change request; only on a writable device.
  const canWriteVlan = device.writable !== false && device.writes_enabled !== false;

  const vlanRows = useMemo(() => {
    const q = vlanFilter.trim().toLowerCase();
    const rows = q
      ? vlans.filter(
          (v) =>
            String(v.vlan_id).includes(q) ||
            v.name.toLowerCase().includes(q) ||
            v.description.toLowerCase().includes(q),
        )
      : vlans;
    return rows;
  }, [vlans, vlanFilter]);

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

  const f = data.facts;
  const factRows: [string, string][] = [
    ['Model', f.model],
    ['OS version', f.os_version],
    ['Serial', f.serial],
    ['Uptime', f.uptime],
    ['License', f.license],
    ['Base MAC', f.base_mac],
    ['Released', f.released],
  ].filter(([, v]) => v) as [string, string][];

  const SUBTABS: { id: SubTab; label: string; icon: React.ReactNode }[] = [
    { id: 'overview', label: 'Overview', icon: <Cpu size={12} /> },
    { id: 'interfaces', label: 'Interfaces', icon: <Router size={12} /> },
    { id: 'vlans', label: 'VLANs', icon: <Layers size={12} /> },
    { id: 'mac', label: 'MAC', icon: <Table2 size={12} /> },
    { id: 'diagnostics', label: 'Diagnostics', icon: <Activity size={12} /> },
  ];

  return (
    <div className="flex h-full flex-col">
      <nav className="flex items-center gap-0.5 border-b border-border px-4 py-2">
        {SUBTABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setSub(t.id)}
            className={cn(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium',
              sub === t.id ? 'bg-bg-elev-2 text-fg' : 'text-fg-muted hover:text-fg',
            )}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </nav>

      <div className="min-h-0 flex-1 overflow-auto nb-scroll px-4 pb-16">
      {sub === 'overview' && (
        <>
      {factRows.length > 0 && (
        <Section title={<SectionTitle icon={<Cpu size={13} className="text-accent" />}>Device</SectionTitle>}>
          <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1 px-1 text-xs">
            {factRows.map(([k, v]) => (
              <KV key={k} label={k}>
                <span className="nb-mono text-fg">{v}</span>
              </KV>
            ))}
          </dl>
        </Section>
      )}
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
        </>
      )}

      {sub === 'interfaces' && (
        <Section
          title={
            <SectionTitle icon={<Router size={13} className="text-accent" />}>
              Interfaces
              <span className="nb-mono ml-1 text-xs text-fg-subtle">{l3.length}</span>
            </SectionTitle>
          }
        >
          {l3.length === 0 ? (
            <p className="px-1 text-xs text-fg-subtle">No addressed interfaces reported.</p>
          ) : (
            <div className="px-1">
              <DataTable
                columns={['Interface', 'Kind', 'IPv4', 'Gateway', 'MTU', 'Notes']}
                rows={l3.map((i) => [
                  i.name,
                  i.kind === 'svi' ? 'L3 SVI' : i.kind === 'management' ? 'Management' : 'LAG',
                  i.ipv4,
                  i.gateway,
                  i.mtu != null ? String(i.mtu) : '',
                  i.enabled ? i.detail : `disabled${i.detail ? ' · ' + i.detail : ''}`,
                ])}
                cellClass={(j) => (j === 0 ? 'text-fg' : j === 2 ? 'text-link' : 'text-fg-muted')}
              />
            </div>
          )}
        </Section>
      )}

      {sub === 'mac' && (
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
      )}

      {sub === 'vlans' && (
      <Section
        title={
          <SectionTitle icon={<Layers size={13} className="text-accent" />}>
            VLANs
            <span className="nb-mono ml-1 text-xs text-fg-subtle">{vlans.length} defined</span>
          </SectionTitle>
        }
        right={
          <span className="flex items-center gap-2">
            {vlans.length > 0 ? (
              <Input
                placeholder="Filter by id / name…"
                value={vlanFilter}
                onChange={(e) => setVlanFilter(e.target.value)}
                className="h-8 w-56 text-xs"
              />
            ) : null}
            {canWriteVlan && (
              <Button
                kind="outline"
                size="sm"
                leftIcon={<Plus size={13} />}
                onClick={() => setAddingVlan((v) => !v)}
              >
                Add VLAN
              </Button>
            )}
          </span>
        }
      >
        {addingVlan && (
          <form
            className="mb-3 flex flex-wrap items-end gap-2 rounded-md border border-accent/30 bg-accent-soft p-3"
            onSubmit={(e) => {
              e.preventDefault();
              const vid = Number.parseInt(newVid, 10);
              if (!Number.isFinite(vid) || vid < 1 || vid > 4094) {
                pushToast({ kind: 'error', title: 'VLAN id must be 1–4094' });
                return;
              }
              createVlan.mutate(
                { device_id: device.id, action: 'create', vlan_id: vid, name: newName || undefined },
                {
                  onSuccess: () => {
                    pushToast({
                      kind: 'success',
                      title: 'VLAN change requested',
                      message: `Create VLAN ${vid} — pending approval`,
                    });
                    setAddingVlan(false);
                    setNewVid('');
                    setNewName('');
                  },
                  onError: (err: unknown) =>
                    pushToast({
                      kind: 'error',
                      title: 'Could not file request',
                      message: err instanceof Error ? err.message : 'Failed',
                    }),
                },
              );
            }}
          >
            <label className="flex flex-col gap-1 text-xs text-fg-muted">
              VLAN id
              <Input
                type="number"
                min={1}
                max={4094}
                value={newVid}
                onChange={(e) => setNewVid(e.target.value)}
                className="h-8 w-28"
                autoFocus
                required
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-fg-muted">
              Name (optional)
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                className="h-8 w-48"
                placeholder="e.g. web-tier"
              />
            </label>
            <Button type="submit" kind="primary" size="sm" disabled={createVlan.isPending}>
              {createVlan.isPending ? 'Filing…' : 'Request VLAN'}
            </Button>
            <Button type="button" kind="ghost" size="sm" onClick={() => setAddingVlan(false)}>
              Cancel
            </Button>
            <span className="basis-full text-[11px] text-fg-subtle">
              Files a change request — an admin approves &amp; applies it (commit-confirm).
            </span>
          </form>
        )}
        {vlans.length === 0 && !addingVlan ? (
          <p className="px-1 text-xs text-fg-subtle">No VLANs reported.</p>
        ) : vlanRows.length === 0 ? (
          <p className="px-1 text-xs text-fg-subtle">No matching VLANs.</p>
        ) : (
          <div className="px-1">
            <DataTable
              columns={['VLAN', 'Name', 'Description', 'L3 (SVI)', 'Ports']}
              rows={vlanRows.map((v) => [
                String(v.vlan_id),
                v.name,
                v.description,
                v.l3_interface,
                String(v.port_count),
              ])}
              cellClass={(j) => (j === 0 ? 'text-fg' : j === 3 ? 'text-link' : 'text-fg-muted')}
            />
          </div>
        )}
      </Section>
      )}

      {sub === 'diagnostics' && (
      <Section
        title={
          <SectionTitle icon={<Activity size={13} className="text-accent" />}>
            Diagnostics &amp; tables
          </SectionTitle>
        }
      >
        <div className="space-y-1 px-1">
          <ProtocolGets deviceId={device.id} slug="Routing" label="IP routing table" />
          <ProtocolGets deviceId={device.id} slug="Optics" label="Transceivers / optics (DOM)" />
          <ProtocolGets deviceId={device.id} slug="Counters" label="Interface traffic counters" />
          <ProtocolGets deviceId={device.id} slug="ARP" label="ARP table" />
        </div>
      </Section>
      )}
      </div>
    </div>
  );
}

/** Lazy-loaded operational tables for a protocol (OSPF neighbors, etc.). */
function ProtocolGets({
  deviceId,
  slug,
  label = 'Operational detail',
}: {
  deviceId: string;
  slug: string;
  label?: string;
}) {
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
        {label}
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
