import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Wordmark } from '@/components/ui/Wordmark';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { useAuthStore } from '@/store/auth';
import { apiClient, isApiError } from '@/api';
import { pushToast } from '@/store/toast';

type Mode = 'signin' | 'register';

export function LoginPage() {
  const navigate = useNavigate();
  const setSession = useAuthStore((s) => s.setSession);
  const [mode, setMode] = useState<Mode>('signin');
  const [username, setUsername] = useState('');
  // Empty by default — never pre-fill a placeholder value. A fake "••••" would
  // be submitted verbatim and (correctly) rejected 401 by the real backend.
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const registering = mode === 'register';

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const result = registering
        ? await apiClient.register(username, password, email || undefined)
        : await apiClient.login(username, password);
      setSession({
        access_token: result.access_token,
        username: result.user.username,
        role: result.user.role,
      });
      navigate('/');
    } catch (err) {
      let message = err instanceof Error ? err.message : 'Unknown error';
      if (isApiError(err)) {
        if (registering) {
          if (err.status === 409) message = 'That username is taken. Try another.';
          else if (err.status === 422)
            message = 'Username needs 3+ characters and password 8+.';
          else if (err.status === 403)
            message = 'Self-registration is disabled. Ask an admin for an account.';
          else if (err.status === 429)
            message = 'Too many attempts. Wait a moment and try again.';
        } else {
          if (err.status === 401) message = 'Invalid username or password.';
          else if (err.status === 429)
            message = 'Too many sign-in attempts. Wait a moment and try again.';
        }
      }
      pushToast({
        kind: 'error',
        title: registering ? 'Registration failed' : 'Sign-in failed',
        message,
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
              autoComplete={registering ? 'new-password' : 'current-password'}
              name="password"
            />
            {registering && (
              <span className="mt-1 block text-[10px] text-fg-subtle">At least 8 characters.</span>
            )}
          </label>
          {registering && (
            <label className="block">
              <span className="mb-1 block text-[11px] uppercase tracking-wider text-fg-subtle">
                Email <span className="text-fg-subtle/70">(optional)</span>
              </span>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                name="email"
              />
            </label>
          )}
        </div>

        <Button
          kind="primary"
          size="lg"
          type="submit"
          disabled={submitting}
          className="nb-reveal w-full"
          style={{ '--nb-reveal-i': 4 } as React.CSSProperties}
        >
          {submitting
            ? registering
              ? 'Creating account…'
              : 'Signing in…'
            : registering
              ? 'Create account'
              : 'Sign in'}
        </Button>

        <div className="text-center text-xs text-fg-muted">
          {registering ? 'Already have an account?' : 'New here?'}{' '}
          <button
            type="button"
            onClick={() => setMode(registering ? 'signin' : 'register')}
            className="font-medium text-accent hover:underline"
          >
            {registering ? 'Sign in' : 'Create a requester account'}
          </button>
        </div>

        <div className="text-center text-[10px] uppercase tracking-wider text-fg-subtle">
          v0.1 · internal
        </div>
      </form>
    </div>
  );
}
