import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  Inbox,
  Info,
  Keyboard,
  ListChecks,
  LogOut,
  Moon,
  Search,
  Settings,
  Sun,
} from 'lucide-react';
import { Wordmark } from '@/components/ui/Wordmark';
import { Kbd } from '@/components/ui/Kbd';
import { Badge } from '@/components/ui/Badge';
import { useAuthStore } from '@/store/auth';
import { useThemeStore } from '@/store/theme';
import { useUIStore } from '@/store/ui';
import { useRequests, useSites } from '@/api/queries';
import { apiClient } from '@/api';
import { initials } from '@/lib/format';
import { PALETTES } from '@/lib/palette';
import { cn } from '@/lib/cn';
import type { Environment } from '@/types';

export function TopBar() {
  const navigate = useNavigate();
  const location = useLocation();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const switchRole = useAuthStore((s) => s.switchRole);
  const env = useUIStore((s) => s.env);
  const setEnv = useUIStore((s) => s.setEnv);
  const openHelp = useUIStore((s) => s.openHelp);
  const theme = useThemeStore((s) => s.theme);
  const palette = useThemeStore((s) => s.palette);
  const setPalette = useThemeStore((s) => s.setPalette);
  const toggleTheme = useThemeStore((s) => s.toggle);

  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const { data: requests = [] } = useRequests();
  const { data: sites = [] } = useSites();
  const pendingCount = requests.filter((r) => r.status === 'pending').length;

  const handleEnvSwitch = (next: Environment) => {
    setEnv(next);
    if (location.pathname.startsWith('/env')) {
      navigate(`/env/${next}`);
    }
  };

  return (
    <header className="sticky top-0 z-40 flex h-14 items-center gap-4 border-b border-border bg-bg/85 px-4 backdrop-blur-md">
      <Link to="/" className="flex items-center gap-2 text-fg hover:text-accent">
        <Wordmark size={15} />
      </Link>

      <nav className="flex items-center gap-1 rounded-md bg-bg-elev-1 p-0.5">
        {sites.map((s) => (
          <button
            key={s.slug}
            type="button"
            onClick={() => handleEnvSwitch(s.slug)}
            title={s.name}
            className={cn(
              'rounded-[4px] px-3 py-1 text-xs font-medium uppercase tracking-wider transition-colors',
              env === s.slug
                ? 'bg-bg-elev-2 text-fg shadow-[0_1px_0_0_rgba(255,255,255,0.04)_inset]'
                : 'text-fg-muted hover:text-fg',
            )}
          >
            {s.name}
          </button>
        ))}
      </nav>

      <div className="ml-2 flex flex-1 items-center justify-center">
        <SearchInput />
      </div>

      <div className="flex items-center gap-1">
        {user?.role === 'admin' && (
          <Link
            to="/queue"
            className={cn(
              'flex h-9 items-center gap-1.5 rounded-md px-2.5 text-sm text-fg-muted hover:bg-bg-elev-2 hover:text-fg',
              location.pathname.startsWith('/queue') && 'bg-bg-elev-2 text-fg',
            )}
          >
            <ListChecks size={14} />
            <span>Queue</span>
            {pendingCount > 0 && <Badge variant="accent">{pendingCount}</Badge>}
          </Link>
        )}
        {user?.role === 'admin' && (
          <Link
            to="/settings"
            className={cn(
              'flex h-9 items-center gap-1.5 rounded-md px-2.5 text-sm text-fg-muted hover:bg-bg-elev-2 hover:text-fg',
              location.pathname.startsWith('/settings') && 'bg-bg-elev-2 text-fg',
            )}
          >
            <Settings size={14} />
            <span>Settings</span>
          </Link>
        )}
        <Link
          to="/requests"
          className={cn(
            'flex h-9 items-center gap-1.5 rounded-md px-2.5 text-sm text-fg-muted hover:bg-bg-elev-2 hover:text-fg',
            location.pathname.startsWith('/requests') && 'bg-bg-elev-2 text-fg',
          )}
        >
          <Inbox size={14} />
          <span>{user?.role === 'admin' ? 'All requests' : 'My requests'}</span>
        </Link>

        {/* Role pill — demo affordance, kept inline for the spec */}
        <div
          role="group"
          aria-label="Role"
          className="ml-1 flex items-center rounded-md border border-border bg-bg-elev-1 p-0.5 text-[11px]"
        >
          <button
            type="button"
            onClick={() => switchRole('admin')}
            className={cn(
              'rounded-[4px] px-2 py-1 uppercase tracking-wider',
              user?.role === 'admin' ? 'bg-bg-elev-2 text-fg' : 'text-fg-muted hover:text-fg',
            )}
          >
            admin
          </button>
          <button
            type="button"
            onClick={() => switchRole('requester')}
            className={cn(
              'rounded-[4px] px-2 py-1 uppercase tracking-wider',
              user?.role === 'requester' ? 'bg-bg-elev-2 text-fg' : 'text-fg-muted hover:text-fg',
            )}
          >
            requester
          </button>
        </div>

        <div ref={menuRef} className="relative">
          <button
            type="button"
            aria-label="Account"
            onClick={() => setMenuOpen((o) => !o)}
            className="ml-1 flex h-9 w-9 items-center justify-center rounded-full border border-border bg-bg-elev-1 text-xs font-semibold text-fg hover:bg-bg-elev-2"
          >
            {user ? initials(user.name) : '?'}
          </button>
          {menuOpen && user && (
            <div className="nb-card absolute right-0 mt-1 w-64 overflow-hidden border-border-strong shadow-xl animate-fade-in">
              <div className="border-b border-border bg-bg-elev-2/40 px-3 py-3">
                <div className="text-sm font-semibold text-fg">{user.name}</div>
                <div className="mt-0.5 text-xs text-fg-muted">
                  {user.role === 'admin' ? 'Admin' : 'Requester'} · @{user.username}
                </div>
              </div>
              <div className="py-1">
                <MenuItem
                  icon={theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
                  label={theme === 'dark' ? 'Light theme' : 'Dark theme'}
                  onClick={() => toggleTheme()}
                />
                <div className="px-3 py-2 text-[10px] uppercase tracking-wider text-fg-subtle">
                  Palette
                </div>
                {Object.values(PALETTES).map((p) => (
                  <button
                    key={p.id}
                    onClick={() => setPalette(p.id)}
                    className={cn(
                      'flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-bg-elev-2',
                      palette === p.id && 'bg-bg-elev-2 text-fg',
                    )}
                  >
                    <span
                      aria-hidden
                      className="inline-block h-3 w-3 rounded-full border border-border-strong"
                      style={{ background: p.accent.dark }}
                    />
                    <span>{p.label}</span>
                  </button>
                ))}
                <div className="my-1 border-t border-border" />
                <MenuItem
                  icon={<Keyboard size={14} />}
                  label="Keyboard shortcuts"
                  trailing={<Kbd>?</Kbd>}
                  onClick={() => {
                    setMenuOpen(false);
                    openHelp();
                  }}
                />
                <MenuItem
                  icon={<Inbox size={14} />}
                  label="My requests"
                  onClick={() => {
                    setMenuOpen(false);
                    navigate('/requests');
                  }}
                />
                <MenuItem
                  icon={<Info size={14} />}
                  label="About Northbound"
                  onClick={() => {
                    setMenuOpen(false);
                    navigate('/about');
                  }}
                />
                <div className="my-1 border-t border-border" />
                <MenuItem
                  icon={<LogOut size={14} />}
                  label="Sign out"
                  onClick={() => {
                    void apiClient.logout();
                    logout();
                    navigate('/login');
                  }}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

function SearchInput() {
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const [value, setValue] = useState('');
  const env = useUIStore((s) => s.env);

  // Listen for `/` shortcut. The hotkey hook in App.tsx focuses .nb-search-input.
  return (
    <div className="flex h-9 w-full max-w-[520px] items-center gap-2 rounded-md border border-border bg-bg-elev-1 px-2.5 text-sm text-fg-muted focus-within:border-accent/60">
      <Search size={14} />
      <input
        ref={inputRef}
        className="nb-search-input flex-1 bg-transparent text-fg placeholder:text-fg-subtle focus:outline-none"
        placeholder="Search ports, VLANs, hosts, BMC IPs…"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && value.trim()) {
            navigate(`/env/${env}/search?q=${encodeURIComponent(value)}`);
          }
        }}
      />
      <Kbd>/</Kbd>
    </div>
  );
}

interface MenuItemProps {
  icon?: React.ReactNode;
  label: string;
  trailing?: React.ReactNode;
  onClick: () => void;
}

function MenuItem({ icon, label, trailing, onClick }: MenuItemProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-fg hover:bg-bg-elev-2"
    >
      <span className="text-fg-muted">{icon}</span>
      <span className="flex-1">{label}</span>
      {trailing}
    </button>
  );
}
