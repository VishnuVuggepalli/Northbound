import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { Gauge, KeyRound, Save, Trash2, UserCheck, UserX, Users } from 'lucide-react';
import { Button } from '@/shared/Button';
import { Input } from '@/shared/Input';
import { Section } from '@/shared/Section';
import { Badge } from '@/shared/Badge';
import { Modal } from '@/modals/Modal';
import {
  useResetUserPassword,
  useSettings,
  useUpdateSettings,
  useUsersAdmin,
  useSetUserActive,
  useDeleteUser,
} from '@/api/queries';
import { useAuthStore } from '@/store/auth';
import { pushToast } from '@/store/toast';
import { isApiError } from '@/api';

const RATE_RE = /^\d+\/(second|minute|hour|day)s?$/i;

/** Admin-only runtime settings. Currently: the write-endpoint rate limit. */
export function SettingsPage() {
  const role = useAuthStore((s) => s.user?.role);
  const { data, isLoading } = useSettings();
  const update = useUpdateSettings();
  const [rate, setRate] = useState('');

  useEffect(() => {
    if (data) setRate(data.write_rate_limit);
  }, [data]);

  if (role !== 'admin') return <Navigate to="/" replace />;

  const valid = RATE_RE.test(rate.trim());
  const dirty = !!data && rate.trim() !== data.write_rate_limit;

  const save = () => {
    update.mutate(
      { write_rate_limit: rate.trim() },
      {
        onSuccess: () => pushToast({ kind: 'success', message: 'Settings saved.' }),
        onError: (e: unknown) => {
          const msg = isApiError(e) && e.status === 422 ? 'Invalid rate limit format.' : 'Save failed.';
          pushToast({ kind: 'error', message: msg });
        },
      },
    );
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-6">
      <div>
        <h1 className="text-lg font-semibold text-fg">Settings</h1>
        <p className="text-sm text-fg-muted">Admin-tunable runtime controls. Changes apply immediately — no redeploy.</p>
      </div>

      <Section title="Rate limiting">
        <div className="flex items-start gap-2 text-xs text-fg-muted">
          <Gauge size={14} className="mt-0.5 shrink-0 text-fg-subtle" />
          <p>
            Caps how many write requests (config pushes, change requests, device edits) a single
            user may make. Format: <code className="nb-mono">count/unit</code> — e.g.{' '}
            <code className="nb-mono">30/minute</code>, <code className="nb-mono">500/hour</code>.
          </p>
        </div>
        <label className="mt-4 flex flex-col gap-1.5">
          <span className="text-[11px] uppercase tracking-wider text-fg-subtle">
            Write rate limit
          </span>
          <div className="flex items-center gap-2">
            <Input
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              placeholder="30/minute"
              className="nb-mono h-8 w-40 text-[12px]"
              disabled={isLoading}
              aria-invalid={!valid}
            />
            <Button
              size="sm"
              leftIcon={<Save size={12} />}
              disabled={!dirty || !valid || update.isPending}
              onClick={save}
            >
              {update.isPending ? 'Saving…' : 'Save'}
            </Button>
          </div>
          {!valid && rate.length > 0 && (
            <span className="text-[10px] text-danger">Use the form count/unit, e.g. 30/minute.</span>
          )}
        </label>
      </Section>

      <Section title="Users">
        <div className="flex items-start gap-2 text-xs text-fg-muted">
          <Users size={14} className="mt-0.5 shrink-0 text-fg-subtle" />
          <p>
            Passwords are stored as one-way hashes — they can never be viewed, only replaced.
            Resetting a password signs the user out of every session. Your own password lives in
            the user menu (top right) → Change password.
          </p>
        </div>
        <UsersTable />
      </Section>
    </div>
  );
}

/** Admin user list with per-row password reset (the old password is never shown
 * or recoverable — bcrypt hashes are one-way). */
function UsersTable() {
  const { data: users = [], isLoading } = useUsersAdmin();
  const reset = useResetUserPassword();
  const active = useSetUserActive();
  const remove = useDeleteUser();
  const me = useAuthStore((s) => s.user?.username);
  const [resetting, setResetting] = useState<string | null>(null);
  const [newPw, setNewPw] = useState('');
  // Delete is irreversible, so it goes through an explicit confirm rather than
  // firing on the first click.
  const [confirmDelete, setConfirmDelete] = useState<{ id: string; username: string } | null>(null);

  const toggleActive = (userId: string, username: string, isActive: boolean) => {
    active.mutate(
      { userId, isActive },
      {
        onSuccess: () =>
          pushToast({
            kind: 'success',
            title: isActive ? 'Account enabled' : 'Account disabled',
            message: isActive
              ? `@${username} can sign in again.`
              : `@${username} was signed out everywhere and can no longer sign in.`,
          }),
        onError: (e: unknown) =>
          pushToast({
            kind: 'error',
            // The server refuses self-disable and last-admin with a 409; surface
            // its reason rather than a generic failure.
            title: 'Could not change account state',
            message: e instanceof Error ? e.message : 'Failed.',
          }),
      },
    );
  };

  const doDelete = () => {
    if (!confirmDelete) return;
    const { id, username } = confirmDelete;
    remove.mutate(id, {
      onSuccess: () => {
        pushToast({
          kind: 'success',
          title: 'User deleted',
          message: `@${username} was removed.`,
        });
        setConfirmDelete(null);
      },
      onError: (e: unknown) => {
        pushToast({
          kind: 'error',
          title: 'Delete failed',
          message: e instanceof Error ? e.message : 'Failed.',
        });
        setConfirmDelete(null);
      },
    });
  };

  const submit = (userId: string, username: string) => {
    reset.mutate(
      { userId, newPassword: newPw },
      {
        onSuccess: () => {
          pushToast({
            kind: 'success',
            title: 'Password reset',
            message: `@${username} was signed out everywhere.`,
          });
          setResetting(null);
          setNewPw('');
        },
        onError: (e: unknown) =>
          pushToast({
            kind: 'error',
            title: 'Reset failed',
            message: e instanceof Error ? e.message : 'Failed.',
          }),
      },
    );
  };

  if (isLoading) return <p className="mt-3 text-xs text-fg-muted">Loading users…</p>;

  return (
    <>
      <ul className="mt-4 divide-y divide-border">
      {users.map((u) => (
        <li key={u.id} className="flex flex-wrap items-center gap-2 py-2">
          <div className="min-w-40">
            <span className="text-sm text-fg">@{u.username}</span>
            {u.username === me && <span className="ml-1 text-[10px] text-fg-subtle">(you)</span>}
            <span className="ml-2 text-[10px] uppercase tracking-wider text-fg-subtle">
              {u.role}
            </span>
            {!u.is_active && (
              <Badge variant="warn" className="ml-2">
                disabled
              </Badge>
            )}
          </div>
          {resetting === u.id ? (
            <form
              className="flex items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (newPw.length >= 8) submit(u.id, u.username);
              }}
            >
              <Input
                type="password"
                value={newPw}
                onChange={(e) => setNewPw(e.target.value)}
                placeholder="New password (min 8)"
                className="h-7 w-48 text-[12px]"
                autoFocus
                aria-label={`New password for ${u.username}`}
              />
              <Button
                size="sm"
                kind="danger"
                type="submit"
                disabled={newPw.length < 8 || reset.isPending}
              >
                {reset.isPending ? 'Resetting…' : 'Reset'}
              </Button>
              <Button
                size="sm"
                kind="ghost"
                type="button"
                onClick={() => {
                  setResetting(null);
                  setNewPw('');
                }}
              >
                Cancel
              </Button>
            </form>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                kind="outline"
                leftIcon={<KeyRound size={12} />}
                onClick={() => {
                  setResetting(u.id);
                  setNewPw('');
                }}
              >
                Reset password…
              </Button>
              {/* Disable is the reversible lever and comes first. Both are
                  hidden on your own row — the server refuses either with a
                  409, so this only avoids offering an action that cannot
                  succeed. */}
              {u.username !== me && (
                <>
                  <Button
                    size="sm"
                    kind="outline"
                    leftIcon={u.is_active ? <UserX size={12} /> : <UserCheck size={12} />}
                    disabled={active.isPending}
                    onClick={() => toggleActive(u.id, u.username, !u.is_active)}
                  >
                    {u.is_active ? 'Disable' : 'Enable'}
                  </Button>
                  <Button
                    size="sm"
                    kind="danger"
                    leftIcon={<Trash2 size={12} />}
                    disabled={remove.isPending}
                    onClick={() => setConfirmDelete({ id: u.id, username: u.username })}
                  >
                    Delete…
                  </Button>
                </>
              )}
            </div>
          )}
        </li>
        ))}
      </ul>

      {/* Delete is irreversible and the id lives on in audit rows and change
          requests, so say that plainly rather than asking "are you sure?". */}
      <Modal
        open={confirmDelete !== null}
        onClose={() => setConfirmDelete(null)}
        title={`Delete @${confirmDelete?.username ?? ''}?`}
      >
        <p className="text-sm text-fg-muted">
          This cannot be undone. Their past change requests and audit entries stay, but will no
          longer show a username.
        </p>
        <p className="mt-2 text-sm text-fg-muted">
          To keep the history readable and reversible, <strong className="text-fg">disable</strong>{' '}
          the account instead — it blocks sign-in immediately and can be undone.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button kind="ghost" onClick={() => setConfirmDelete(null)}>
            Cancel
          </Button>
          <Button
            kind="outline"
            onClick={() => {
              if (confirmDelete) toggleActive(confirmDelete.id, confirmDelete.username, false);
              setConfirmDelete(null);
            }}
          >
            Disable instead
          </Button>
          <Button kind="danger" disabled={remove.isPending} onClick={doDelete}>
            {remove.isPending ? 'Deleting…' : 'Delete permanently'}
          </Button>
        </div>
      </Modal>
    </>
  );
}
