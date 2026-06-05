import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { Gauge, Save } from 'lucide-react';
import { Button } from '@/shared/Button';
import { Input } from '@/shared/Input';
import { Section } from '@/shared/Section';
import { useSettings, useUpdateSettings } from '@/api/queries';
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
    </div>
  );
}
