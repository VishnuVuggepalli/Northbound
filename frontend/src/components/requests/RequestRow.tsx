import { useState } from 'react';
import { ArrowRight, ChevronDown, ChevronRight, ExternalLink, History } from 'lucide-react';
import { Button } from '@/shared/Button';
import { Textarea } from '@/shared/Input';
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
  // Called unconditionally (before the early return) to keep hook order stable
  // across renders — react-hooks/rules-of-hooks. A conditional hook crashes the
  // row to blank once data loads.
  const { data: platforms } = usePlatforms();
  const isAdmin = user.role === 'admin';
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
                  <Button kind="danger" size="sm" onClick={() => setRejecting(true)}>
                    Reject…
                  </Button>
                </>
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

