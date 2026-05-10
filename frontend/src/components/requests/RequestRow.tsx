import { useState } from 'react';
import { ArrowRight, ChevronDown, ChevronRight, ExternalLink, History } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Textarea } from '@/components/ui/Input';
import { VlanChip } from '@/components/ui/VlanChip';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { Badge } from '@/components/ui/Badge';
import { Diff, ConfigDiff } from '@/components/Diff';
import { ApplyConfirmModal } from '@/components/requests/ApplyConfirmModal';
import { applyChangeToPort, mergeChange, portToRequestedChanges } from '@/lib/config';
import { timeAgo } from '@/lib/format';
import type { ThemeMode } from '@/lib/palette';
import type { ChangeRequest, Device, Port, User } from '@/types';
import { cn } from '@/lib/cn';

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
  onOpenPort,
  lastBackupAgoMs = 4 * 60 * 60 * 1000,
}: RequestRowProps) {
  const [rejecting, setRejecting] = useState(false);
  const [comment, setComment] = useState('');
  const [confirmingApply, setConfirmingApply] = useState(false);
  const isAdmin = user.role === 'admin';
  if (!device || !port) return null;
  const after = applyChangeToPort(port, request.requested_changes);
  // router / vpn devices are read-only regardless of role; the device header
  // already shows a "Read-only" badge but the queue row would otherwise still
  // expose Approve & apply. Mirror the badge here so the apply path is a hard
  // block, not a soft warning. Approve-only stays available so admins can
  // still triage the queue.
  const isWriteLocked = device.role === 'router' || device.role === 'vpn';

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
          <span>@{request.requested_by}</span>
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
                  : device.platform === 'mikrotik'
                    ? ' with safe-mode + manual rollback (no commit-confirm)'
                    : ' with commit-confirm 60s'}
                .
              </span>
            </div>
          )}
          <KV label="Reason" value={request.reason} />
          {request.reviewer_comment && (
            <KV label="Reviewer comment" value={request.reviewer_comment} />
          )}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wider text-fg-subtle">
                Field changes
              </div>
              <Diff
                before={portToRequestedChanges(port)}
                after={mergeChange(port, request.requested_changes)}
              />
            </div>
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wider text-fg-subtle">
                Rendered config delta
              </div>
              <ConfigDiff device={device} portBefore={port} portAfter={after} />
            </div>
          </div>

          {rejecting ? (
            <div className="space-y-2 rounded-md border border-danger/30 bg-danger/5 p-3">
              <Textarea
                autoFocus
                rows={2}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder={`Required: tell @${request.requested_by} why and what to do.`}
              />
              <div className="flex justify-end gap-1.5">
                <Button
                  kind="ghost"
                  size="sm"
                  onClick={() => {
                    setRejecting(false);
                    setComment('');
                  }}
                >
                  Cancel
                </Button>
                <Button
                  kind="danger"
                  size="sm"
                  disabled={!comment.trim()}
                  onClick={() => {
                    onReject?.(request.id, comment.trim());
                    setRejecting(false);
                    setComment('');
                  }}
                >
                  Confirm reject
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
                  {!isWriteLocked && (
                    <Button
                      kind="success"
                      size="sm"
                      onClick={() => setConfirmingApply(true)}
                      data-testid="approve-apply"
                    >
                      Approve &amp; apply
                    </Button>
                  )}
                  <Button kind="danger" size="sm" onClick={() => setRejecting(true)}>
                    Reject…
                  </Button>
                </>
              )}
              {isAdmin && request.status === 'approved' && !isWriteLocked && (
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

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="mb-0.5 text-[10px] uppercase tracking-wider text-fg-subtle">{label}</div>
      <div className="text-sm text-fg">{value}</div>
    </div>
  );
}
