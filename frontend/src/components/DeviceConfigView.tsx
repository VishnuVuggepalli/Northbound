import { useMemo, useState } from 'react';
import { AlertTriangle, History, Loader2, RefreshCw, Search } from 'lucide-react';
import { Button } from '@/shared/Button';
import { Input } from '@/shared/Input';
import { useBackupDiff, useBackupNow, useDeviceBackups, useDeviceConfig } from '@/api/queries';
import { isApiError } from '@/api';
import { pushToast } from '@/store/toast';
import { timeAgo } from '@/lib/format';
import { cn } from '@/lib/cn';
import type { Device, User } from '@/models';

interface DeviceConfigViewProps {
  device: Device;
  user: User;
}

export function DeviceConfigView({ device, user }: DeviceConfigViewProps) {
  const isAdmin = user.role === 'admin';
  const [query, setQuery] = useState('');
  const [showDiff, setShowDiff] = useState(false);

  // The real device config (full NETCONF/NAPALM dump) + stored backups. Gated
  // on isAdmin so non-admins (who get the placeholder below) never fetch.
  const config = useDeviceConfig(device.id, isAdmin);
  const backups = useDeviceBackups(device.id, isAdmin);
  const backupNow = useBackupNow(device.id);
  const latestBackup = backups.data?.[0];
  const diff = useBackupDiff(device.id, latestBackup?.id, showDiff && isAdmin);

  const lines = useMemo(
    () => (config.data?.config_text ?? '').split('\n'),
    [config.data],
  );
  const filteredIdx = useMemo(() => {
    if (!query) return null;
    const q = query.toLowerCase();
    const set = new Set<number>();
    lines.forEach((l, i) => {
      if (l.toLowerCase().includes(q)) set.add(i);
    });
    return set;
  }, [query, lines]);

  if (!isAdmin) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center text-fg-muted">
        <div className="text-base font-semibold text-fg">Admin-only view</div>
        <div className="text-sm">
          The full running config is admin-only.<br />
          Per-port snippets remain visible in the port detail panel.
        </div>
      </div>
    );
  }

  const runBackup = () => {
    backupNow.mutate(undefined, {
      onSuccess: () => pushToast({ kind: 'success', title: 'Backup taken', message: device.name }),
      onError: (err) =>
        pushToast({
          kind: 'error',
          title: 'Backup failed',
          message: isApiError(err) ? err.message : 'Could not reach the device',
        }),
    });
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <div className="flex h-9 flex-1 items-center gap-2 rounded-md border border-border bg-bg-elev-1 px-2.5 text-sm">
          <Search size={14} className="text-fg-muted" />
          <Input
            placeholder={`Search running config of ${device.name}…`}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="border-0 bg-transparent p-0 focus-visible:ring-0"
          />
        </div>
        <Button
          kind="ghost"
          size="sm"
          leftIcon={<History size={14} />}
          disabled={!latestBackup}
          title={latestBackup ? undefined : 'No backups yet — take one first'}
          onClick={() => setShowDiff((v) => !v)}
        >
          {showDiff ? 'Hide diff' : 'Compare to last backup'}
        </Button>
        <Button
          kind="ghost"
          size="sm"
          leftIcon={<RefreshCw size={14} className={cn(config.isFetching && 'animate-spin')} />}
          disabled={config.isFetching}
          onClick={() => config.refetch()}
        >
          Refresh
        </Button>
        <Button
          kind="ghost"
          size="sm"
          leftIcon={<History size={14} className={cn(backupNow.isPending && 'animate-pulse')} />}
          disabled={backupNow.isPending}
          onClick={runBackup}
        >
          Backup now
        </Button>
        <span className="text-xs text-fg-subtle">
          {backups.isLoading
            ? 'loading backups…'
            : latestBackup
              ? `last backup · ${timeAgo(Date.parse(latestBackup.fetched_at))}`
              : 'no backups yet'}
        </span>
      </header>
      <div className="min-h-0 flex-1 overflow-auto nb-scroll pb-16">
        {config.isLoading ? (
          <div className="flex h-full items-center justify-center gap-2 text-sm text-fg-muted">
            <Loader2 size={16} className="animate-spin" />
            Fetching running config from {device.name}…
          </div>
        ) : config.isError ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
            <AlertTriangle size={20} className="text-danger" />
            <div className="text-sm text-fg">
              Couldn’t fetch the running config from {device.name}.
              <div className="mt-1 text-xs text-fg-muted">
                {isApiError(config.error) ? config.error.message : 'Device unreachable'}
              </div>
            </div>
            <Button kind="outline" size="sm" onClick={() => config.refetch()}>
              Retry
            </Button>
          </div>
        ) : showDiff ? (
          <BackupDiffPanel
            device={device}
            loading={diff.isLoading}
            error={diff.isError ? (isApiError(diff.error) ? diff.error.message : 'Diff failed') : null}
            diffText={diff.data?.diff ?? ''}
            backupAgeMs={latestBackup ? Date.parse(latestBackup.fetched_at) : null}
          />
        ) : (
          <pre className="nb-mono w-full bg-bg-elev-1/40 p-3 text-[11px] leading-relaxed">
            <code>
              {lines.map((line, i) => (
                <div
                  key={i}
                  className={cn(
                    'flex gap-3',
                    filteredIdx && !filteredIdx.has(i) && 'opacity-30',
                    filteredIdx && filteredIdx.has(i) && 'bg-warn/10',
                  )}
                >
                  <span className="w-10 shrink-0 select-none text-right text-fg-subtle">
                    {i + 1}
                  </span>
                  <span className="whitespace-pre-wrap text-fg">
                    <SyntaxLine line={line} platform={device.platform} />
                  </span>
                </div>
              ))}
            </code>
          </pre>
        )}
      </div>
    </div>
  );
}

interface BackupDiffPanelProps {
  device: Device;
  loading: boolean;
  error: string | null;
  diffText: string;
  backupAgeMs: number | null;
}

/** Renders the unified diff (backup → live) with +/- line coloring. */
function BackupDiffPanel({ device, loading, error, diffText, backupAgeMs }: BackupDiffPanelProps) {
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-fg-muted">
        <Loader2 size={16} className="animate-spin" />
        Diffing against last backup…
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center text-sm text-fg">
        <AlertTriangle size={18} className="text-danger" />
        {error}
      </div>
    );
  }
  const diffLines = diffText.split('\n');
  return (
    <div className="p-4">
      {diffText.trim() === '' ? (
        <div className="rounded-md border border-border bg-bg-elev-1/40 p-4 text-sm text-fg-muted">
          No changes since the last backup
          {backupAgeMs != null ? ` (${timeAgo(backupAgeMs)})` : ''}.
        </div>
      ) : (
        <pre className="nb-mono w-full bg-bg-elev-1/40 p-3 text-[11px] leading-relaxed">
          <code>
            {diffLines.map((line, i) => (
              <div
                key={i}
                className={cn(
                  'whitespace-pre-wrap',
                  line.startsWith('+') && !line.startsWith('+++') && 'text-ok',
                  line.startsWith('-') && !line.startsWith('---') && 'text-danger',
                  line.startsWith('@@') && 'text-accent',
                )}
              >
                {line || ' '}
              </div>
            ))}
          </code>
        </pre>
      )}
      <div className="mt-2 text-xs text-fg-subtle">
        Diff of {device.name}: last backup → current running config.
      </div>
    </div>
  );
}

const KEYWORDS: Record<Device['platform'], string[]> = {
  cisco: ['interface', 'description', 'no', 'shutdown', 'switchport', 'mode', 'access', 'trunk', 'native', 'vlan', 'allowed', 'router', 'bgp', 'neighbor', 'hostname'],
  arista: ['interface', 'description', 'no', 'shutdown', 'switchport', 'mode', 'access', 'trunk', 'native', 'vlan', 'allowed', 'router', 'bgp', 'neighbor', 'hostname'],
  pica8: ['set', 'interface', 'description', 'enable', 'disable', 'vlans', 'tagged', 'untagged', 'protocols', 'system'],
  mikrotik: ['/interface', '/system', '/ip', 'bridge', 'port', 'vlan', 'set', 'find', 'comment', 'pvid', 'disabled', 'address', 'identity'],
  mikrotik_swos: ['SwOS', 'identity', 'version', 'serial', 'mgmt-ip', 'up', 'enabled', 'disabled', 'read-only'],
  freebsd: ['ifconfig_', 'inet', 'up', 'down', 'mtu', 'pf', 'rc.conf', 'frr', 'router', 'bgp', 'hostname', 'gateway_enable'],
  mock: ['interface', 'vlan', 'hostname'],
};

function SyntaxLine({ line, platform }: { line: string; platform: Device['platform'] }) {
  if (/^\s*[#!;]/.test(line)) {
    return <span className="text-fg-subtle">{line}</span>;
  }
  const parts = line.split(/(".*?")/g);
  const kws = KEYWORDS[platform];
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('"')) {
          return (
            <span key={i} className="text-warn">
              {part}
            </span>
          );
        }
        return part.split(/(\s+)/).map((tok, j) => {
          if (/^\s+$/.test(tok)) return <span key={`${i}.${j}`}>{tok}</span>;
          if (/^\d+(\.\d+){0,3}(\/\d+)?$/.test(tok.trim())) {
            return (
              <span key={`${i}.${j}`} className="text-accent">
                {tok}
              </span>
            );
          }
          if (kws.some((k) => tok === k || tok.startsWith(k))) {
            return (
              <span key={`${i}.${j}`} className="font-semibold text-link">
                {tok}
              </span>
            );
          }
          return <span key={`${i}.${j}`}>{tok}</span>;
        });
      })}
    </>
  );
}
