import { useEffect, useRef } from 'react';
import { AlertTriangle } from 'lucide-react';
import { Modal } from '@/components/ui/Modal';
import { Button } from '@/components/ui/Button';
import { ConfigDiff } from '@/components/Diff';
import { applyChangeToPort } from '@/lib/config';
import type { ChangeRequest, Device, Port } from '@/types';

interface ApplyConfirmModalProps {
  open: boolean;
  request: ChangeRequest;
  device: Device;
  port: Port;
  onCancel: () => void;
  onConfirm: () => void;
}

/**
 * Confirmation gate before an admin pushes a change to a device.
 *
 * Reuses:
 *   - <Modal>            for the dialog shell + a11y / Esc / focus trap
 *   - <Button>           for the action row (danger + ghost variants)
 *   - <ConfigDiff>       for the inline-rendered config delta (same component
 *                        used everywhere else so the user sees identical
 *                        formatting whether they're previewing or confirming)
 *   - lucide AlertTriangle for the spine warning glyph (no inline SVG)
 *
 * Spine devices keep the modal but get an inline warning band — they're
 * write-allowed but blast radius is leaf reachability. Router/VPN are
 * write-locked upstream and never reach this modal at all.
 */
export function ApplyConfirmModal({
  open,
  request,
  device,
  port,
  onCancel,
  onConfirm,
}: ApplyConfirmModalProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const portAfter = applyChangeToPort(port, request.requested_changes);
  const isSpine = device.role === 'spine';

  // Focus the safer (Cancel) action by default per UX-instructor "error
  // prevention" — the destructive option must be the deliberate one.
  useEffect(() => {
    if (!open) return;
    const id = window.setTimeout(() => cancelRef.current?.focus(), 30);
    return () => window.clearTimeout(id);
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onCancel}
      width={620}
      title={`Apply change to ${device.name} / ${port.name}?`}
      subtitle={`Pushing #${request.id} live to ${device.platform} (${device.role}). Review the rendered delta before confirming.`}
      footer={
        <>
          <Button ref={cancelRef} kind="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            kind="danger"
            leftIcon={<AlertTriangle size={14} />}
            onClick={onConfirm}
            data-testid="apply-confirm"
          >
            Apply now
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {isSpine && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-warn/40 bg-[var(--nb-warn-soft)] px-3 py-2 text-xs text-fg"
          >
            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-warn" />
            <span>
              Spine changes affect leaf reachability — confirm with care.
            </span>
          </div>
        )}
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wider text-fg-subtle">
            Rendered config delta
          </div>
          <ConfigDiff device={device} portBefore={port} portAfter={portAfter} />
        </div>
      </div>
    </Modal>
  );
}
