import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Wordmark } from '@/components/ui/Wordmark';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { useAuthStore } from '@/store/auth';
import { apiClient, USE_MOCKS } from '@/api';
import { pushToast } from '@/store/toast';

export function LoginPage() {
  const navigate = useNavigate();
  const setSession = useAuthStore((s) => s.setSession);
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('••••••••');
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const result = await apiClient.login(username, password);
      setSession({
        access_token: result.access_token,
        username: result.user.username,
        role: result.user.role,
      });
      navigate('/');
    } catch (err) {
      pushToast({
        kind: 'error',
        title: 'Sign-in failed',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="nb-atmos nb-grid nb-grain flex min-h-screen items-center justify-center p-6">
      <form
        onSubmit={submit}
        className="nb-card nb-reveal w-full max-w-md space-y-5 border-border-strong p-7"
        style={{ '--nb-reveal-i': 1 } as React.CSSProperties}
      >
        <div className="nb-reveal flex flex-col items-center gap-2" style={{ '--nb-reveal-i': 2 } as React.CSSProperties}>
          <Wordmark size={26} animate />
          <div className="nb-mono text-[10px] uppercase tracking-[0.22em] text-fg-subtle">
            SDN management plane
          </div>
        </div>

        <div className="nb-reveal space-y-3" style={{ '--nb-reveal-i': 3 } as React.CSSProperties}>
          <label className="block">
            <span className="mb-1 block text-[11px] uppercase tracking-wider text-fg-subtle">
              Username
            </span>
            <Input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              autoComplete="username"
              name="username"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] uppercase tracking-wider text-fg-subtle">
              Password
            </span>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              name="password"
            />
          </label>
        </div>

        <Button
          kind="primary"
          size="lg"
          type="submit"
          disabled={submitting}
          className="nb-reveal w-full"
          style={{ '--nb-reveal-i': 4 } as React.CSSProperties}
        >
          {submitting ? 'Signing in…' : 'Sign in'}
        </Button>

        {USE_MOCKS && (
          <div className="rounded-md border border-border bg-bg-elev-1 px-3 py-2 text-xs text-fg-muted">
            Try <code className="nb-mono text-accent">admin</code> or{' '}
            <code className="nb-mono text-accent">alice</code>. Mock auth — any password works.
          </div>
        )}

        <div className="text-center text-[10px] uppercase tracking-wider text-fg-subtle">
          v0.1 · internal
        </div>
      </form>
    </div>
  );
}
