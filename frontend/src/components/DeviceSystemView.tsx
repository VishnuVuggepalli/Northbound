import { useMemo, useState } from 'react';
import { Activity, ChevronDown, ChevronRight, Cpu, Layers, Loader2, Network, Router, ShieldCheck, Table2 } from 'lucide-react';
import {
  useCreateL3Request,
  useCreateOspfRequest,
  useCreateVlanRequest,
  useL3Interfaces,
  useOspfInterfaces,
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
import { Pencil, Plus, Trash2 } from 'lucide-react';
import { pushToast } from '@/store/toast';
import { cn } from '@/lib/cn';
import type { Device } from '@/models';
import {
  EMPTY_L3_FORM,
  EMPTY_OSPF_FORM,
  EMPTY_VLAN_FORM,
  filingErrorToast,
  type L3FormInitial,
  type OspfFormInitial,
  type VlanFormInitial,
} from '@/components/device-system/support';
import { VlanForm } from '@/components/device-system/VlanForm';
import { L3Form } from '@/components/device-system/L3Form';
import { OspfForm } from '@/components/device-system/OspfForm';
import { VrfForm } from '@/components/device-system/VrfForm';

type SubTab = 'overview' | 'interfaces' | 'vlans' | 'mac' | 'diagnostics';

/** Inline-form opener: non-null mounts the form pre-filled; `seq` keys the form
 *  so an Edit click re-seeds the fields even while the form is already open. */
type FormState<T> = { seq: number; initial: T } | null;

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
  const { data: ospfIfaces = [] } = useOspfInterfaces(device.id);
  const [macFilter, setMacFilter] = useState('');
  const [vlanFilter, setVlanFilter] = useState('');
  const [sub, setSub] = useState<SubTab>('overview');
  // Mutations for the inline delete confirmations (the create/edit forms own
  // their own mutation instances — see components/device-system/).
  const createVlan = useCreateVlanRequest();
  const createL3 = useCreateL3Request();
  const createOspf = useCreateOspfRequest();
  const [vlanForm, setVlanForm] = useState<FormState<VlanFormInitial>>(null);
  const [l3Form, setL3Form] = useState<FormState<L3FormInitial>>(null);
  const [ospfForm, setOspfForm] = useState<FormState<OspfFormInitial>>(null);
  const [addingVrf, setAddingVrf] = useState(false);
  const [deleteVid, setDeleteVid] = useState<number | null>(null);
  const [deleteL3, setDeleteL3] = useState<
    { kind: 'svi' | 'loopback'; vid?: number; name?: string; label: string } | null
  >(null);
  const openVlanForm = (initial: VlanFormInitial) =>
    setVlanForm((f) => ({ seq: (f?.seq ?? 0) + 1, initial }));
  const openL3Form = (initial: L3FormInitial) =>
    setL3Form((f) => ({ seq: (f?.seq ?? 0) + 1, initial }));
  const openOspfForm = (initial: OspfFormInitial) =>
    setOspfForm((f) => ({ seq: (f?.seq ?? 0) + 1, initial }));
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
          right={
            canWriteVlan ? (
              <span className="flex items-center gap-2">
                <Button
                  kind="outline"
                  size="sm"
                  leftIcon={<Plus size={13} />}
                  onClick={() => setAddingVrf((v) => !v)}
                >
                  Add VRF
                </Button>
                <Button
                  kind="outline"
                  size="sm"
                  leftIcon={<Plus size={13} />}
                  onClick={() => (l3Form ? setL3Form(null) : openL3Form(EMPTY_L3_FORM))}
                >
                  Add L3
                </Button>
                <Button
                  kind="outline"
                  size="sm"
                  leftIcon={<Plus size={13} />}
                  onClick={() => (ospfForm ? setOspfForm(null) : openOspfForm(EMPTY_OSPF_FORM))}
                >
                  OSPF
                </Button>
              </span>
            ) : undefined
          }
        >
          {ospfForm && (
            <OspfForm
              key={ospfForm.seq}
              deviceId={device.id}
              initial={ospfForm.initial}
              onClose={() => setOspfForm(null)}
            />
          )}
          {addingVrf && <VrfForm deviceId={device.id} onClose={() => setAddingVrf(false)} />}
          {l3Form && (
            <L3Form
              key={l3Form.seq}
              deviceId={device.id}
              initial={l3Form.initial}
              onClose={() => setL3Form(null)}
            />
          )}
          {l3.length === 0 && !l3Form ? (
            <p className="px-1 text-xs text-fg-subtle">No addressed interfaces reported.</p>
          ) : (
            <div className="px-1">
              {deleteL3 !== null && (
                <div className="mb-3 flex flex-wrap items-center gap-3 rounded-md border border-danger/40 bg-danger/5 p-3 text-sm">
                  <span className="text-fg">
                    Delete <span className="nb-mono font-semibold">{deleteL3.label}</span>? Files a
                    change request.
                  </span>
                  <span className="ml-auto flex gap-1.5">
                    <Button kind="ghost" size="sm" onClick={() => setDeleteL3(null)}>
                      Cancel
                    </Button>
                    <Button
                      kind="danger"
                      size="sm"
                      disabled={createL3.isPending}
                      onClick={() =>
                        createL3.mutate(
                          {
                            device_id: device.id,
                            action: 'delete',
                            kind: deleteL3.kind,
                            vlan_id: deleteL3.vid,
                            name: deleteL3.name,
                          },
                          {
                            onSuccess: () => {
                              pushToast({ kind: 'success', title: `${deleteL3.label} delete requested` });
                              setDeleteL3(null);
                            },
                            onError: filingErrorToast,
                          },
                        )
                      }
                    >
                      Request delete
                    </Button>
                  </span>
                </div>
              )}
              <DataTable
                columns={
                  canWriteVlan
                    ? ['Interface', 'Kind', 'IPv4', 'Gateway', 'MTU', 'Notes', '']
                    : ['Interface', 'Kind', 'IPv4', 'Gateway', 'MTU', 'Notes']
                }
                rowKeys={l3.map((i) => i.name)}
                rows={l3.map((i) => {
                  const base = [
                    i.name,
                    i.kind === 'svi'
                      ? 'L3 SVI'
                      : i.kind === 'loopback'
                        ? 'Loopback'
                        : i.kind === 'management'
                          ? 'Management'
                          : 'LAG',
                    i.ipv4 || null,
                    i.gateway || null,
                    i.mtu != null ? String(i.mtu) : null,
                    i.enabled ? i.detail || null : `disabled${i.detail ? ' · ' + i.detail : ''}`,
                  ];
                  if (!canWriteVlan) return base;
                  // SVIs + loopbacks are user-managed via our change model (mgmt/LAG aren't).
                  const vid = i.kind === 'svi' ? Number.parseInt(i.name.replace(/\D/g, ''), 10) : NaN;
                  const editable =
                    (i.kind === 'svi' && Number.isFinite(vid)) || i.kind === 'loopback';
                  return [
                    ...base,
                    editable ? (
                      <span key="act" className="flex items-center gap-2">
                        <button
                          type="button"
                          title={`Edit ${i.name}`}
                          aria-label={`Edit ${i.name}`}
                          onClick={() =>
                            openL3Form({
                              kind: i.kind === 'svi' ? 'svi' : 'loopback',
                              vid: i.kind === 'svi' ? String(vid) : '',
                              name: i.kind === 'loopback' ? i.name : '',
                              ip: i.ipv4,
                              mtu: i.mtu != null ? String(i.mtu) : '',
                              vrf: '',
                            })
                          }
                          className="text-fg-subtle transition-colors hover:text-accent"
                        >
                          <Pencil size={13} />
                        </button>
                        <button
                          type="button"
                          title={`Delete ${i.name}`}
                          aria-label={`Delete ${i.name}`}
                          onClick={() =>
                            setDeleteL3(
                              i.kind === 'svi'
                                ? { kind: 'svi', vid, label: i.name }
                                : { kind: 'loopback', name: i.name, label: i.name },
                            )
                          }
                          className="text-fg-subtle transition-colors hover:text-danger"
                        >
                          <Trash2 size={13} />
                        </button>
                      </span>
                    ) : (
                      ''
                    ),
                  ];
                })}
                cellClass={(j) => (j === 0 ? 'text-fg' : j === 2 ? 'text-link' : 'text-fg-muted')}
              />
            </div>
          )}
          {ospfIfaces.length > 0 && (
            <div className="mt-5 px-1">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-fg-subtle">
                OSPF interfaces
              </div>
              <DataTable
                columns={
                  canWriteVlan
                    ? ['Interface', 'Area', 'Cost', 'Hello', 'Dead', 'Passive', '']
                    : ['Interface', 'Area', 'Cost', 'Hello', 'Dead', 'Passive']
                }
                rowKeys={ospfIfaces.map((o) => o.name)}
                rows={ospfIfaces.map((o) => {
                  const base = [
                    o.name,
                    o.area || null,
                    o.cost != null ? String(o.cost) : null,
                    o.hello_interval != null ? String(o.hello_interval) : null,
                    o.dead_interval != null ? String(o.dead_interval) : null,
                    o.passive ? 'yes' : null,
                  ];
                  if (!canWriteVlan) return base;
                  return [
                    ...base,
                    <span key="act" className="flex items-center gap-2">
                      <button
                        type="button"
                        title={`Edit OSPF ${o.name}`}
                        aria-label={`Edit OSPF ${o.name}`}
                        onClick={() =>
                          openOspfForm({
                            target: 'interface',
                            iface: o.name,
                            area: o.area,
                            routerId: '',
                            cost: o.cost != null ? String(o.cost) : '',
                          })
                        }
                        className="text-fg-subtle transition-colors hover:text-accent"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        type="button"
                        title={`Remove ${o.name} from OSPF`}
                        aria-label={`Remove ${o.name} from OSPF`}
                        onClick={() =>
                          createOspf.mutate(
                            {
                              device_id: device.id,
                              action: 'delete',
                              target: 'interface',
                              interface: o.name,
                            },
                            {
                              onSuccess: () =>
                                pushToast({
                                  kind: 'success',
                                  title: `OSPF remove ${o.name} requested`,
                                }),
                              onError: filingErrorToast,
                            },
                          )
                        }
                        className="text-fg-subtle transition-colors hover:text-danger"
                      >
                        <Trash2 size={13} />
                      </button>
                    </span>,
                  ];
                })}
                cellClass={(j) => (j === 0 ? 'text-fg' : 'text-fg-muted')}
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
              // (vlan, mac) is the natural FDB key — stable under live filtering.
              rowKeys={macRows.map((r) => `${r.vlan ?? '-'}|${r.mac}`)}
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
                onClick={() => (vlanForm ? setVlanForm(null) : openVlanForm(EMPTY_VLAN_FORM))}
              >
                Add VLAN
              </Button>
            )}
          </span>
        }
      >
        {vlanForm && (
          <VlanForm
            key={vlanForm.seq}
            deviceId={device.id}
            initial={vlanForm.initial}
            onClose={() => setVlanForm(null)}
          />
        )}
        {deleteVid !== null && (
          <div className="mb-3 flex flex-wrap items-center gap-3 rounded-md border border-danger/40 bg-danger/5 p-3 text-sm">
            <span className="text-fg">
              Delete VLAN <span className="nb-mono font-semibold">{deleteVid}</span>? This files a
              change request for admin approval.
            </span>
            <span className="ml-auto flex gap-1.5">
              <Button kind="ghost" size="sm" onClick={() => setDeleteVid(null)}>
                Cancel
              </Button>
              <Button
                kind="danger"
                size="sm"
                disabled={createVlan.isPending}
                onClick={() =>
                  createVlan.mutate(
                    { device_id: device.id, action: 'delete', vlan_id: deleteVid },
                    {
                      onSuccess: () => {
                        pushToast({
                          kind: 'success',
                          title: 'VLAN delete requested',
                          message: `Delete VLAN ${deleteVid} — pending approval`,
                        });
                        setDeleteVid(null);
                      },
                      onError: filingErrorToast,
                    },
                  )
                }
              >
                Request delete
              </Button>
            </span>
          </div>
        )}
        {vlans.length === 0 && !vlanForm ? (
          <p className="px-1 text-xs text-fg-subtle">No VLANs reported.</p>
        ) : vlanRows.length === 0 ? (
          <p className="px-1 text-xs text-fg-subtle">No matching VLANs.</p>
        ) : (
          <div className="px-1">
            <DataTable
              columns={
                canWriteVlan
                  ? ['VLAN', 'Name', 'Description', 'L3 (SVI)', 'Ports', '']
                  : ['VLAN', 'Name', 'Description', 'L3 (SVI)', 'Ports']
              }
              rowKeys={vlanRows.map((v) => v.vlan_id)}
              rows={vlanRows.map((v) => {
                const base = [
                  String(v.vlan_id),
                  v.name || null,
                  v.description || null,
                  v.l3_interface || null,
                  String(v.port_count),
                ];
                if (!canWriteVlan) return base;
                return [
                  ...base,
                  <span key="act" className="flex items-center gap-2">
                    <button
                      type="button"
                      title={`Edit VLAN ${v.vlan_id}`}
                      aria-label={`Edit VLAN ${v.vlan_id}`}
                      onClick={() => {
                        // Pre-fill the Add form → submit re-applies (edit-config
                        // merges, so this updates name/description in place).
                        openVlanForm({
                          vid: String(v.vlan_id),
                          name: v.name,
                          desc: v.description,
                        });
                      }}
                      className="text-fg-subtle transition-colors hover:text-accent"
                    >
                      <Pencil size={13} />
                    </button>
                    {/* VLAN 1 (default) is not deletable on most platforms. */}
                    {v.vlan_id !== 1 && (
                      <button
                        type="button"
                        title={`Delete VLAN ${v.vlan_id}`}
                        aria-label={`Delete VLAN ${v.vlan_id}`}
                        onClick={() => setDeleteVid(v.vlan_id)}
                        className="text-fg-subtle transition-colors hover:text-danger"
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </span>,
                ];
              })}
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
                <DataTable
                  columns={t.columns}
                  // API rows use '' for "no value" — map to null so the em dash shows.
                  rows={t.rows.map((row) => row.map((c) => (c === '' ? null : c)))}
                />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
