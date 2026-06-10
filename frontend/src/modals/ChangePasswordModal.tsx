import { useState } from 'react';
import { KeyRound } from 'lucide-react';
import { Modal } from '@/modals/Modal';
import { Button } from '@/shared/Button';
import { Input } from '@/shared/Input';
import { useChangeMyPassword } from '@/api/queries';
import { pushToast } from '@/store/toast';

interface ChangePasswordModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Self-service password change (any role), opened from the user menu.
 *
 * Requires the current password (a hijacked cookie alone can't take over the
 * account). The backend bumps the token version — killing every other session
 * — and re-issues fresh cookies, so THIS session survives the change.
 */
export function ChangePasswordModal({ open, onClose }: ChangePasswordModalProps) {
  const change = useChangeMyPassword();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');

  const mismatch = confirm.length > 0 && next !== confirm;
  const tooShort = next.length > 0 && next.length < 8;
  const ready = current.length > 0 && next.length >= 8 && next === confirm && !change.isPending;

  const reset = () => {
    setCurrent('');
    setNext('');
    setConfirm('');
  };

  const submit = () => {
    change.mutate(
      { currentPassword: current, newPassword: next },
      {
        onSuccess: () => {
          pushToast({
            kind: 'success',
            title: 'Password changed',
            message: 'Other sessions were signed out.',
          });
          reset();
          onClose();
        },
        onError: (e: unknown) =>
          pushToast({
            kind: 'error',
            title: 'Password change failed',
            message: e instanceof Error ? e.message : 'Failed.',
          }),
      },
    );
  };

  return (
    <Modal
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title={
        <span className="flex items-center gap-2">
          <KeyRound size={14} /> Change password
        </span>
      }
      subtitle="Changing your password signs out every other session."
    >
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) submit();
        }}
      >
        <label className="block">
          <span className="mb-1 block text-[11px] uppercase tracking-wider text-fg-subtle">
            Current password
          </span>
          <Input
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
            autoFocus
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] uppercase tracking-wider text-fg-subtle">
            New password
          </span>
          <Input
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
            aria-invalid={tooShort}
          />
          {tooShort && (
            <span className="mt-1 block text-[10px] text-danger">At least 8 characters.</span>
          )}
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] uppercase tracking-wider text-fg-subtle">
            Confirm new password
          </span>
          <Input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            aria-invalid={mismatch}
          />
          {mismatch && (
            <span className="mt-1 block text-[10px] text-danger">Passwords do not match.</span>
          )}
        </label>
        <div className="flex justify-end gap-2 pt-1">
          <Button kind="ghost" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button kind="primary" size="sm" type="submit" disabled={!ready}>
            {change.isPending ? 'Changing…' : 'Change password'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
