import { useEffect, useState } from 'react';
import { AlertCircle, Clock, Network, Pencil, RefreshCw, Send, X } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Input, Textarea } from '@/components/ui/Input';
import { Section } from '@/components/ui/Section';
import { KV } from '@/components/ui/KV';
import { StatusDot } from '@/components/ui/StatusDot';
import { VlanChip } from '@/components/ui/VlanChip';
import { Kbd } from '@/components/ui/Kbd';
import { Diff } from '@/components/Diff';
import { PortConfigEditor } from '@/components/PortConfigEditor';
import { VendorActions } from '@/components/VendorActions';
import { portToRequestedChanges, mergeChange } from '@/lib/config';
import { fmtAge, formatSpeed, timeAgo, timeAgoMin } from '@/lib/format';
import type { ThemeMode } from '@/lib/palette';
import type {
  AuditEntry,
  ChangeRequest,
  Device,
  Port,
  User,
} from '@/types';
import {
  useApplyRequest,
  usePlatforms,
  useRejectRequest,
  useSetPortDescription,
  useUpdatePortMetadata,
} from '@/api/queries';
import { pushToast } from '@/store/toast';
import { findPlatformForDevice, isWriteLocked } from '@/lib/devicePolicy';

interface PortPanelProps {
  device: Device;
  port: Port;
  requests: ChangeRequest[];
  audit: AuditEntry[];
  theme: ThemeMode;
  user: User;
  /** Wall-clock ms when the live data was last fetched (TanStack dataUpdatedAt). */
  fetchedAt?: number;
  onClose: () => void;
  onOpenRequest: () => void;
  onRefetch: () => void;
}

/** Cache TTL — when the React Query cache considers a port snapshot fresh. */
const CACHE_TTL_MS = 30_000;
/** Stale threshold — at this age we surface an amber warning band. */
const STALE_THRESHOLD_MS = 60_000;
/** Tick interval for the live "X ago" label. 5s is human-readable without
 *  burning frames; the threshold transitions are still visible within one
 *  tick of crossing 30s and 60s. */
const TICK_INTERVAL_MS = 5_000;

export function PortPanel({
  device,
  port,
  requests,
  audit,
  theme,
  user,
  fetchedAt,
  onClose,
  onOpenRequest,
  onRefetch,
}: PortPanelProps) {
  // Tick periodically so "X ago" stays honest without re-fetching. 5s is the
  // sweet spot: granular enough that the user notices the 30s/60s transitions
  // within one tick, gentle enough not to burn frames.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), TICK_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, []);
  const ageMs = fetchedAt ? Math.max(0, now - fetchedAt) : null;
  const stale = ageMs != null && ageMs > STALE_THRESHOLD_MS;
  const aging = ageMs != null && ageMs > CACHE_TTL_MS && ageMs <= STALE_THRESHOLD_MS;
  const { data: platforms } = usePlatforms();
  const platform = findPlatformForDevice(device, platforms ?? []);
  const writeLocked = isWriteLocked(device, platform);
  const isAdmin = user.role === 'admin';
  const showNeighbors =
    (platform?.capabilities.supports_lldp ?? false) && (port.neighbors?.length ?? 0) > 0;
  const pending = requests.filter(
    (r) =>
      r.device_id === device.id && r.port_name === port.name && r.status === 'pending',
  );
  const portAudit = audit
    .filter((a) => a.device_id === device.id && a.port_name === port.name)
    .slice(0, 6);

  const apply = useApplyRequest();
  const reject = useRejectRequest();
  const updateMeta = useUpdatePortMetadata(device.id);

  // Notes editing (admin-only). Local draft seeded from the port; reset when the
  // selected port changes (key on the aside remounts, but guard anyway).
  const [editingNotes, setEditingNotes] = useState(false);
  const [notesDraft, setNotesDraft] = useState(port.notes ?? '');
  const saveNotes = () => {
    updateMeta.mutate(
      { portName: port.name, patch: { notes: notesDraft } },
      {
        onSuccess: () => {
          setEditingNotes(false);
          pushToast({ kind: 'success', message: 'Notes saved.' });
        },
        onError: (e: unknown) =>
          pushToast({ kind: 'error', message: e instanceof Error ? e.message : 'Save failed.' }),
      },
    );
  };

  // Description editing (admin-only). DIRECT device write — commits immediately,
  // not a change request. Read-locked devices are rejected by the backend.
  const setDesc = useSetPortDescription(device.id);
  const [editingDesc, setEditingDesc] = useState(false);
  const [descDraft, setDescDraft] = useState(port.description ?? '');
  const saveDesc = () => {
    setDesc.mutate(
      { portName: port.name, description: descDraft },
      {
        onSuccess: () => {
          setEditingDesc(false);
          pushToast({ kind: 'success', message: 'Description written to device.' });
        },
        onError: (e: unknown) =>
          pushToast({ kind: 'error', message: e instanceof Error ? e.message : 'Write failed.' }),
      },
    );
  };

  return (
    <aside
      key={`${device.id}:${port.name}`}
      className="absolute right-0 top-0 z-30 flex h-full w-[480px] max-w-[95vw] flex-col border-l border-border bg-bg-elev-1 shadow-2xl animate-slide-in-right"
    >
      <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <div className="nb-mono flex items-center gap-1 text-[11px] text-fg-muted">
            <span>{device.name}</span>
            <span>›</span>
            <span>{port.name}</span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-base font-semibold text-fg">
            <StatusDot
              state={port.state}
              pulse={port.state === 'up' && port.traffic > 0.4}
              size={10}
            />
            <span>
              {port.state === 'up'
                ? 'Link up'
                : port.state === 'down'
                  ? 'No link'
                  : 'Admin disabled'}
            </span>
            <span className="ml-1 text-xs font-normal text-fg-muted">on VLAN</span>
            <VlanChip vlan={port.untagged_vlan} theme={theme} />
          </div>
        </div>
        <button
          type="button"
          aria-label="Close panel"
          onClick={onClose}
          className="rounded-md p-1 text-fg-muted hover:bg-bg-elev-2 hover:text-fg"
        >
          <X size={16} />
        </button>
      </header>

      {/* Freshness status row. Sits directly under the header so the user's eye
       *  catches the stale state before reading any field. Three visual states:
       *  fresh (≤30s, fg-subtle), aging (30-60s, fg-muted), stale (>60s, amber
       *  band with refetch CTA). aria-live so AT users hear transitions. */}
      {ageMs != null && (stale ? (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center justify-between gap-2 border-b border-warn/40 bg-[var(--nb-warn-soft)] px-4 py-2 text-xs text-fg"
          data-testid="port-stale-band"
        >
          <span className="flex items-center gap-1.5">
            <AlertCircle size={12} className="text-warn" aria-hidden />
            <span>Data may be stale (last fetched {fmtAge(ageMs)}). Refetch?</span>
          </span>
          <Button kind="ghost" size="sm" onClick={onRefetch} leftIcon={<RefreshCw size={12} />}>
            Refetch
          </Button>
        </div>
      ) : (
        <div
          aria-live="polite"
          className={
            'flex items-center gap-1.5 border-b border-border px-4 py-1.5 text-[11px] ' +
            (aging ? 'text-fg-muted' : 'text-fg-subtle')
          }
          data-testid="port-fresh-status"
        >
          <Clock size={11} aria-hidden />
          <span>Last fetched {fmtAge(ageMs)} · cache TTL 30s</span>
        </div>
      ))}

      <div className="nb-scroll flex-1 space-y-1 overflow-y-auto px-4">
        <Section title="Overview">
          <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1.5 text-xs">
            {isAdmin && (
              <KV label="Description">
                {editingDesc ? (
                  <span className="flex items-center gap-1.5">
                    <Input
                      value={descDraft}
                      onChange={(e) => setDescDraft(e.target.value)}
                      aria-label="Port description"
                      className="h-7 flex-1 text-[11px]"
                    />
                    <Button size="sm" onClick={saveDesc} disabled={setDesc.isPending}>
                      {setDesc.isPending ? '…' : 'Write'}
                    </Button>
                    <button
                      type="button"
                      onClick={() => setEditingDesc(false)}
                      className="text-xs text-fg-subtle hover:text-fg"
                    >
                      Cancel
                    </button>
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5">
                    <span className="nb-mono text-[11px]">{port.description || '—'}</span>
                    <button
                      type="button"
                      title="Edit description (writes to device)"
                      onClick={() => {
                        setDescDraft(port.description ?? '');
                        setEditingDesc(true);
                      }}
                      className="text-accent hover:text-fg"
                    >
                      <Pencil size={11} />
                    </button>
                  </span>
                )}
              </KV>
            )}
            <KV label="Host model">{port.host_model || '—'}</KV>
            <KV label="BMC IP">
              <span className="nb-mono text-[11px]">{port.bmc_ip || '—'}</span>
            </KV>
            <KV label="MAC">
              <span className="nb-mono text-[11px]">{port.mac || '—'}</span>
            </KV>
            <KV label="Speed">{formatSpeed(port.speed_mbps)}</KV>
            <KV label="Duplex">{port.duplex ?? '—'}</KV>
            <KV label="MTU">{port.mtu}</KV>
          </dl>
          <div className="mt-3 rounded-md border border-border bg-bg-elev-1 p-2.5 text-xs">
            <div className="flex items-center justify-between">
              <div className="text-[10px] uppercase tracking-wider text-fg-subtle">Notes</div>
              {isAdmin && !editingNotes && (
                <button
                  type="button"
                  onClick={() => {
                    setNotesDraft(port.notes ?? '');
                    setEditingNotes(true);
                  }}
                  className="flex items-center gap-1 text-[10px] text-accent hover:underline"
                >
                  <Pencil size={10} /> Edit
                </button>
              )}
            </div>
            {editingNotes ? (
              <div className="mt-1.5 space-y-1.5">
                <Textarea
                  value={notesDraft}
                  onChange={(e) => setNotesDraft(e.target.value)}
                  rows={3}
                  placeholder="Operational notes for this port…"
                  className="text-[11px]"
                />
                <div className="flex items-center gap-2">
                  <Button size="sm" onClick={saveNotes} disabled={updateMeta.isPending}>
                    {updateMeta.isPending ? 'Saving…' : 'Save'}
                  </Button>
                  <button
                    type="button"
                    onClick={() => setEditingNotes(false)}
                    className="text-xs text-fg-subtle hover:text-fg"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="mt-1 text-fg">
                {port.notes || <em className="text-fg-subtle">No notes</em>}
              </div>
            )}
          </div>
        </Section>

        <Section title={isAdmin && !writeLocked ? 'VLANs & port config' : 'VLANs'}>
          {isAdmin && !writeLocked ? (
            <PortConfigEditor deviceId={device.id} port={port} />
          ) : (
            <>
              <div className="mb-2 flex items-center gap-3">
                <span className="w-20 text-[11px] uppercase tracking-wider text-fg-subtle">
                  Untagged
                </span>
                <VlanChip vlan={port.untagged_vlan} theme={theme} large />
              </div>
              <div className="flex items-center gap-3">
                <span className="w-20 text-[11px] uppercase tracking-wider text-fg-subtle">
                  Tagged
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {port.tagged_vlans.length === 0 ? (
                    <span className="text-xs text-fg-muted">none</span>
                  ) : (
                    port.tagged_vlans.map((v) => <VlanChip key={v} vlan={v} theme={theme} />)
                  )}
                </div>
              </div>
            </>
          )}
        </Section>

        {showNeighbors && (
          <Section title="Neighbor (LLDP)">
            <ul className="space-y-1.5">
              {port.neighbors!.map((n, idx) => (
                <li
                  key={`${n.chassis_id}-${n.port_id}-${idx}`}
                  className="flex items-start gap-2 rounded-md border border-border bg-bg-elev-1 px-2.5 py-1.5 text-xs"
                  title={n.system_description ?? undefined}
                >
                  <Network size={12} className="mt-0.5 shrink-0 text-fg-muted" aria-hidden />
                  <div className="min-w-0 flex-1 space-y-0.5">
                    <div className="flex items-center gap-1.5">
                      <span className="text-fg">{n.system_name || <em className="text-fg-subtle">unknown system</em>}</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-fg-muted">
                      <span className="nb-mono">{n.chassis_id}</span>
                      <span>›</span>
                      <span className="nb-mono">{n.port_id}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {Object.keys(port.services).length > 0 && (
          <Section title="Services">
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(port.services).map(([k, on]) => (
                <span
                  key={k}
                  className={`flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${
                    on
                      ? 'border-success/30 bg-success/10 text-success'
                      : 'border-border bg-bg-elev-1 text-fg-subtle'
                  }`}
                >
                  <StatusDot state={on ? 'up' : 'off'} size={5} />
                  <span>{k.toUpperCase()}</span>
                </span>
              ))}
            </div>
          </Section>
        )}

        <Section title="Pending requests" defaultOpen={pending.length > 0}>
          {pending.length === 0 ? (
            <div className="text-xs text-fg-muted">No open requests on this port.</div>
          ) : (
            pending.map((req) => (
              <div
                key={req.id}
                className="mb-2 rounded-md border border-warn/40 bg-warn/5 p-2.5 last:mb-0"
              >
                <div className="nb-mono mb-2 flex items-center gap-2 text-[11px] text-fg-muted">
                  <span className="font-semibold text-fg">#{req.id}</span>
                  <span>·</span>
                  <span>@{req.requested_by}</span>
                  <span>·</span>
                  <span>{timeAgo(req.created_at)}</span>
                </div>
                <Diff
                  before={portToRequestedChanges(port)}
                  after={mergeChange(port, req.requested_changes)}
                  compact
                />
                {isAdmin && (
                  <div className="mt-2 flex gap-1.5">
                    {!writeLocked && (
                      <Button
                        kind="success"
                        size="sm"
                        onClick={() => {
                          apply.mutate(
                            { id: req.id, reviewer: user.username },
                            {
                              onSuccess: () =>
                                pushToast({
                                  kind: 'success',
                                  title: 'Applied',
                                  message: `#${req.id} pushed to ${device.name}`,
                                }),
                            },
                          );
                        }}
                      >
                        Approve & apply
                      </Button>
                    )}
                    <Button
                      kind="ghost"
                      size="sm"
                      onClick={() => {
                        reject.mutate(
                          {
                            id: req.id,
                            reviewer: user.username,
                            comment: 'Rejected from port panel',
                          },
                          {
                            onSuccess: () =>
                              pushToast({
                                kind: 'info',
                                title: 'Rejected',
                                message: `#${req.id} sent back to @${req.requested_by}`,
                              }),
                          },
                        );
                      }}
                    >
                      Reject
                    </Button>
                  </div>
                )}
              </div>
            ))
          )}
        </Section>

        <Section title="History">
          {portAudit.length === 0 ? (
            <div className="text-xs text-fg-muted">No recent activity on this port.</div>
          ) : (
            <ul className="space-y-1.5 text-xs">
              {portAudit.map((a) => (
                <li
                  key={a.id}
                  className="flex items-baseline gap-2 border-b border-border pb-1.5 last:border-b-0"
                >
                  <span className="w-10 shrink-0 text-fg-subtle">{timeAgoMin(a.ago_minutes)}</span>
                  <span className="text-fg-muted">@{a.user}</span>
                  <span className="text-fg">{a.summary}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>

      <footer className="flex items-center justify-between gap-2 border-t border-border bg-bg-elev-1/60 px-4 py-3">
        <div className="flex items-center gap-2">
        {isAdmin ? (
          <>
            {pending.length > 0 && !writeLocked && (
              <Button
                kind="success"
                onClick={() => {
                  const target = pending[0]!;
                  apply.mutate(
                    { id: target.id, reviewer: user.username },
                    {
                      onSuccess: () =>
                        pushToast({
                          kind: 'success',
                          title: 'Applied',
                          message: `#${target.id} pushed to ${device.name}`,
                        }),
                    },
                  );
                }}
              >
                Apply pending
              </Button>
            )}
            <Button kind="ghost" leftIcon={<RefreshCw size={14} />} onClick={onRefetch}>
              Refetch
            </Button>
          </>
        ) : (
          !writeLocked && (
            <Button kind="primary" leftIcon={<Send size={14} />} onClick={onOpenRequest}>
              Request change <Kbd>r</Kbd>
            </Button>
          )
        )}
        </div>
        <VendorActions device={device} platform={platform} />
      </footer>
    </aside>
  );
}

