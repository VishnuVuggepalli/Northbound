import { useState } from 'react';
import { ArrowRight, ChevronDown, ChevronRight, ExternalLink, History } from 'lucide-react';
import { Button } from '@/shared/Button';
import { Input, Textarea } from '@/shared/Input';
import { VlanChip } from '@/shared/VlanChip';
import { StatusBadge } from '@/shared/StatusBadge';
import { Badge } from '@/shared/Badge';
import { KV } from '@/shared/KV';
import { Diff, ConfigDiff } from '@/components/Diff';
import { ApplyConfirmModal } from '@/modals/ApplyConfirmModal';
import { applyChangeToPort, mergeChange, portToRequestedChanges } from '@/lib/config';
import { timeAgo } from '@/lib/format';
import type { ThemeMode } from '@/lib/palette';
import type { ChangeRequest, Device, Port, User } from '@/models';
import { cn } from '@/lib/cn';
import { isWriteLocked, findPlatformForDevice } from '@/lib/devicePolicy';
import { usePlatforms } from '@/api/queries';

type Mode = 'mine' | 'queue';

interface RequestRowProps {
  request: ChangeRequest;
  device: Device | undefined;
  port: Port | undefined;
  theme: ThemeMode;
  user: User;
  mode: Mode;
  expanded: boolean;
  onToggle: () => void;
  onApprove?: (id: string) => void;
  onApply?: (id: string) => void;
  onReject?: (id: string, comment: string) => void;
  onRequestChanges?: (id: string, comment: string) => void;
  onResubmit?: (id: string, input: { untagged_vlan?: number; reason?: string }) => void;
  onOpenPort?: (deviceId: string, portName: string, env: Device['env']) => void;
  lastBackupAgoMs?: number;
}

export function RequestRow({
  request,
  device,
  port,
  theme,
  user,
  mode,
  expanded,
  onToggle,
  onApprove,
  onApply,
  onReject,
  onRequestChanges,
  onResubmit,
  onOpenPort,
  lastBackupAgoMs = 4 * 60 * 60 * 1000,
}: RequestRowProps) {
  // One comment box serves both reject and request-changes (same UX).
  const [panel, setPanel] = useState<null | 'reject' | 'changes'>(null);
  const [comment, setComment] = useState('');
  const [resubmitting, setResubmitting] = useState(false);
  const [resubVlan, setResubVlan] = useState(String(request.requested_changes.untagged_vlan ?? ''));
  const [resubReason, setResubReason] = useState(request.reason);
  const [confirmingApply, setConfirmingApply] = useState(false);
  // Called unconditionally (before the early return) to keep hook order stable
  // across renders — react-hooks/rules-of-hooks. A conditional hook crashes the
  // row to blank once data loads.
  const { data: platforms } = usePlatforms();
  const isAdmin = user.role === 'admin';
  const requesterLabel = request.requested_by_username ?? request.requested_by.slice(0, 8);
  if (!device || !port) return null;
  const after = applyChangeToPort(port, request.requested_changes);
  // Write-lock check is centralized in lib/devicePolicy. Combines role
  // (router/vpn) with platform capability (writable=false on SwOS+FreeBSD).
  // Approve-only stays available so admins can still triage the queue; the
  // apply path is a hard block.
  const platform = findPlatformForDevice(device, platforms ?? []);
  const writeLocked = isWriteLocked(device, platform);

  return (
    <div
      className={cn(
        'overflow-hidden rounded-lg border border-border transition-colors',
        expanded && 'border-border-strong bg-bg-elev-1',
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        className="grid w-full grid-cols-[40px_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] items-center gap-3 px-3 py-2.5 text-left hover:bg-bg-elev-1"
      >
        <span className="flex items-center gap-1 nb-mono text-[11px] text-fg-muted">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <span className="font-semibold text-fg">#{request.id}</span>
        </span>
        <span className="flex items-center gap-1.5 text-xs">
          <Badge variant="muted">{device.env}</Badge>
          <span className="nb-mono truncate text-fg">{device.name}</span>
          <ChevronRight size={11} className="shrink-0 text-fg-subtle" />
          <span className="nb-mono truncate text-fg">{request.port_name}</span>
        </span>
        <span className="flex items-center gap-1.5">
          <VlanChip vlan={port.untagged_vlan} theme={theme} />
          <ArrowRight size={11} className="text-fg-subtle" />
          <VlanChip vlan={request.requested_changes.untagged_vlan} theme={theme} />
          {request.requested_changes.tagged_vlans?.length ? (
            <Badge variant="muted" className="ml-1">
              +{request.requested_changes.tagged_vlans.length}T
            </Badge>
          ) : null}
        </span>
        <span className="flex items-center justify-end gap-2 text-xs text-fg-muted">
          {/* Prefer the resolved username; fall back to a short id (e.g. if the
              user was deleted) rather than a full UUID. */}
          <span title={request.requested_by}>
            @{request.requested_by_username ?? request.requested_by.slice(0, 8)}
          </span>
          <span>·</span>
          <span>{timeAgo(request.created_at)}</span>
          <StatusBadge status={request.status} />
        </span>
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-border bg-bg p-4">
          {mode === 'queue' && (
            <div className="flex items-center gap-2 rounded-md border border-warn/30 bg-warn/5 px-3 py-2 text-xs text-fg">
              <History size={12} className="text-warn" />
              <span>
                Last backup of <strong>{device.name}</strong>: {timeAgo(Date.now() - lastBackupAgoMs)}
              </span>
              <span className="text-fg-subtle">·</span>
              <span className="text-fg-muted">
                Apply runs <em>backup → diff → push</em>
                {device.platform === 'freebsd'
                  ? ' (FreeBSD is read-only)'
                  : ' with commit-confirm 60s'}
                .
              </span>
            </div>
          )}
          <KV label="Reason" variant="stacked">{request.reason}</KV>
          {request.reviewer_comment && (
            <KV label="Reviewer comment" variant="stacked">{request.reviewer_comment}</KV>
          )}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <KV label="Field changes" variant="stacked">
              <Diff
                before={portToRequestedChanges(port)}
                after={mergeChange(port, request.requested_changes)}
              />
            </KV>
            <KV label="Rendered config delta" variant="stacked">
              <ConfigDiff device={device} portBefore={port} portAfter={after} />
            </KV>
          </div>

          {panel !== null ? (
            <div
              className={cn(
                'space-y-2 rounded-md border p-3',
                panel === 'reject' ? 'border-danger/30 bg-danger/5' : 'border-warn/40 bg-warn/5',
              )}
            >
              <Textarea
                autoFocus
                rows={2}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder={
                  panel === 'reject'
                    ? `Required: tell @${requesterLabel} why this is rejected.`
                    : `Required: tell @${requesterLabel} what to change and why.`
                }
              />
              <div className="flex justify-end gap-1.5">
                <Button kind="ghost" size="sm" onClick={() => { setPanel(null); setComment(''); }}>
                  Cancel
                </Button>
                <Button
                  kind={panel === 'reject' ? 'danger' : 'primary'}
                  size="sm"
                  disabled={!comment.trim()}
                  onClick={() => {
                    if (panel === 'reject') onReject?.(request.id, comment.trim());
                    else onRequestChanges?.(request.id, comment.trim());
                    setPanel(null);
                    setComment('');
                  }}
                >
                  {panel === 'reject' ? 'Confirm reject' : 'Send for revision'}
                </Button>
              </div>
            </div>
          ) : resubmitting ? (
            <div className="space-y-2 rounded-md border border-accent/30 bg-accent-soft p-3">
              <div className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2">
                <label htmlFor={`resub-vlan-${request.id}`} className="text-xs text-fg-muted">
                  Untagged VLAN
                </label>
                <Input
                  id={`resub-vlan-${request.id}`}
                  type="number"
                  value={resubVlan}
                  onChange={(e) => setResubVlan(e.target.value)}
                  className="h-8 w-32"
                />
                <label htmlFor={`resub-reason-${request.id}`} className="text-xs text-fg-muted">
                  Reason
                </label>
                <Input
                  id={`resub-reason-${request.id}`}
                  value={resubReason}
                  onChange={(e) => setResubReason(e.target.value)}
                  className="h-8"
                />
              </div>
              <div className="flex justify-end gap-1.5">
                <Button kind="ghost" size="sm" onClick={() => setResubmitting(false)}>
                  Cancel
                </Button>
                <Button
                  kind="primary"
                  size="sm"
                  onClick={() => {
                    const v = Number.parseInt(resubVlan, 10);
                    onResubmit?.(request.id, {
                      untagged_vlan: Number.isFinite(v) ? v : undefined,
                      reason: resubReason.trim() || undefined,
                    });
                    setResubmitting(false);
                  }}
                >
                  Resubmit for review
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-end gap-2">
              {onOpenPort && (
                <Button
                  kind="link"
                  size="sm"
                  rightIcon={<ExternalLink size={12} />}
                  onClick={() => onOpenPort(device.id, request.port_name, device.env)}
                >
                  Open port
                </Button>
              )}
              {isAdmin && request.status === 'pending' && (
                <>
                  <Button kind="ghost" size="sm" onClick={() => onApprove?.(request.id)}>
                    Approve only
                  </Button>
                  {!writeLocked && (
                    <Button
                      kind="success"
                      size="sm"
                      onClick={() => setConfirmingApply(true)}
                      data-testid="approve-apply"
                    >
                      Approve &amp; apply
                    </Button>
                  )}
                  <Button kind="outline" size="sm" onClick={() => setPanel('changes')}>
                    Request changes…
                  </Button>
                  <Button kind="danger" size="sm" onClick={() => setPanel('reject')}>
                    Reject…
                  </Button>
                </>
              )}
              {/* Owner revises after a request-changes. Non-admins only ever
                  receive their OWN requests (backend-scoped), so !isAdmin == owner. */}
              {!isAdmin && request.status === 'needs_revision' && (
                <Button kind="primary" size="sm" onClick={() => setResubmitting(true)}>
                  Edit &amp; resubmit
                </Button>
              )}
              {isAdmin && request.status === 'approved' && !writeLocked && (
                <Button
                  kind="success"
                  size="sm"
                  onClick={() => setConfirmingApply(true)}
                  data-testid="apply-now"
                >
                  Apply now
                </Button>
              )}
            </div>
          )}
        </div>
      )}
      {isAdmin && (
        <ApplyConfirmModal
          open={confirmingApply}
          request={request}
          device={device}
          port={port}
          onCancel={() => setConfirmingApply(false)}
          onConfirm={() => {
            setConfirmingApply(false);
            onApply?.(request.id);
          }}
        />
      )}
    </div>
  );
}

