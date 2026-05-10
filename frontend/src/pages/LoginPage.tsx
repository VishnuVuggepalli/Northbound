import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Wordmark } from '@/components/ui/Wordmark';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { useAuthStore } from '@/store/auth';
import { login as loginApi } from '@/api/client';
import { pushToast } from '@/store/toast';

export function LoginPage() {
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('••••••••');
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const result = await loginApi(username, password);
      login(result.user.username);
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
    <div className="flex min-h-screen items-center justify-center bg-bg p-6">
      <form
        onSubmit={submit}
        className="nb-card w-full max-w-md space-y-5 border-border-strong p-6 shadow-2xl animate-fade-in"
      >
        <div className="flex flex-col items-center gap-1.5">
          <Wordmark size={22} />
          <div className="text-xs uppercase tracking-wider text-fg-subtle">
            SDN management plane
          </div>
        </div>

        <div className="space-y-3">
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

        <Button kind="primary" size="lg" type="submit" disabled={submitting} className="w-full">
          {submitting ? 'Signing in…' : 'Sign in'}
        </Button>

        <div className="rounded-md border border-border bg-bg-elev-1 px-3 py-2 text-xs text-fg-muted">
          Try <code className="nb-mono text-accent">admin</code> or{' '}
          <code className="nb-mono text-accent">alice</code>. Mock auth — any password works.
        </div>

        <div className="text-center text-[10px] uppercase tracking-wider text-fg-subtle">
          v0.1 · internal
        </div>
      </form>
    </div>
  );
}
