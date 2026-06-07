import { cn } from '@/lib/cn';
import { renderConfigSnippet } from '@/lib/config';
import type { Device, Port, RequestedChanges } from '@/models';

interface DiffProps {
  before: Required<RequestedChanges>;
  after: Required<RequestedChanges>;
  compact?: boolean;
}

const KEYS: Array<keyof RequestedChanges> = [
  'untagged_vlan',
  'tagged_vlans',
  'host_model',
  'bmc_ip',
  'notes',
];

const LABELS: Record<keyof RequestedChanges, string> = {
  untagged_vlan: 'untagged',
  tagged_vlans: 'tagged',
  host_model: 'host',
  bmc_ip: 'bmc',
  notes: 'notes',
};

function fmt(v: unknown): string {
  if (Array.isArray(v)) return v.length ? v.join(',') : '—';
  if (v === '' || v == null) return '—';
  return String(v);
}

export function Diff({ before, after, compact }: DiffProps) {
  return (
    <div className={cn('overflow-hidden rounded-md border border-border', compact && 'text-xs')}>
      <table className="w-full table-fixed">
        <tbody>
          {KEYS.map((k) => {
            const a = JSON.stringify(before[k]);
            const b = JSON.stringify(after[k]);
            const changed = a !== b;
            return (
              <tr
                key={k}
                className={cn(
                  'border-b border-border last:border-b-0',
                  changed && 'bg-warn/5',
                )}
              >
                <td className="nb-mono w-20 border-r border-border px-2 py-1.5 text-[10px] uppercase tracking-wider text-fg-subtle">
                  {LABELS[k]}
                </td>
                <td className="nb-mono px-2 py-1.5 text-[11px]">
                  <span
                    className={cn(
                      'mr-1 inline-block w-3 text-center',
                      changed ? 'text-danger' : 'text-fg-subtle',
                    )}
                  >
                    -
                  </span>
                  <span className={changed ? 'text-fg' : 'text-fg-muted'}>{fmt(before[k])}</span>
                </td>
                <td className="nb-mono px-2 py-1.5 text-[11px]">
                  <span
                    className={cn(
                      'mr-1 inline-block w-3 text-center',
                      changed ? 'text-success' : 'text-fg-subtle',
                    )}
                  >
                    +
                  </span>
                  <span className={changed ? 'font-semibold text-fg' : 'text-fg-muted'}>
                    {fmt(after[k])}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface ConfigDiffProps {
  device: Device;
  portBefore: Port;
  portAfter: Port;
}

export function ConfigDiff({ device, portBefore, portAfter }: ConfigDiffProps) {
  const before = renderConfigSnippet(device, portBefore).split('\n');
  const after = renderConfigSnippet(device, portAfter).split('\n');
  const max = Math.max(before.length, after.length);
  const lines: Array<{ kind: 'eq' | 'add' | 'rem'; text: string }> = [];
  for (let i = 0; i < max; i++) {
    const a = before[i] ?? '';
    const b = after[i] ?? '';
    if (a === b) {
      lines.push({ kind: 'eq', text: a });
    } else {
      if (a) lines.push({ kind: 'rem', text: a });
      if (b) lines.push({ kind: 'add', text: b });
    }
  }
  return (
    <pre className="nb-mono overflow-x-auto rounded-md border border-border bg-bg-elev-1 px-3 py-2 text-[11px] leading-relaxed">
      <code>
        {lines.map((l, i) => (
          <div
            key={i}
            className={cn(
              'flex items-start gap-2',
              l.kind === 'add' && 'bg-success/10 text-success',
              l.kind === 'rem' && 'bg-danger/10 text-danger',
              l.kind === 'eq' && 'text-fg-muted',
            )}
          >
            <span className="w-3 shrink-0 select-none text-center">
              {l.kind === 'add' ? '+' : l.kind === 'rem' ? '-' : ' '}
            </span>
            <span className="whitespace-pre-wrap">{l.text}</span>
          </div>
        ))}
      </code>
    </pre>
  );
}
