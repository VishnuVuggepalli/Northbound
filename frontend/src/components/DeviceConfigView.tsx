import { useMemo, useState } from 'react';
import { History, RefreshCw, Search } from 'lucide-react';
import { Button } from '@/shared/Button';
import { Input } from '@/shared/Input';
import { ConfigDiff } from './Diff';
import { renderFullConfig } from '@/lib/config';
import { cn } from '@/lib/cn';
import type { Device, Port, User } from '@/models';

interface DeviceConfigViewProps {
  device: Device;
  ports: Port[];
  user: User;
}

export function DeviceConfigView({ device, ports, user }: DeviceConfigViewProps) {
  const isAdmin = user.role === 'admin';
  const [query, setQuery] = useState('');
  const [showDiff, setShowDiff] = useState(false);

  const lines = useMemo(() => renderFullConfig(device, ports), [device, ports]);
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
          onClick={() => setShowDiff((v) => !v)}
        >
          {showDiff ? 'Hide diff' : 'Compare to last backup'}
        </Button>
        <Button kind="ghost" size="sm" leftIcon={<RefreshCw size={14} />}>
          Backup now
        </Button>
        <span className="text-xs text-fg-subtle">last backup · 2 h ago</span>
      </header>
      <div className="min-h-0 flex-1 overflow-auto nb-scroll pb-16">
        {showDiff && ports.length > 0 ? (
          <div className="p-4">
            <ConfigDiff
              device={device}
              portBefore={{ ...ports[0]!, description: '' }}
              portAfter={ports[0]!}
            />
            <div className="mt-2 text-xs text-fg-subtle">
              Showing illustrative diff against the most recent backup of {device.name}.
            </div>
          </div>
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
