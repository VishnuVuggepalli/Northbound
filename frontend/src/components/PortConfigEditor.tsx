import { useEffect, useState } from 'react';
import { Power, Save } from 'lucide-react';
import { Button } from '@/shared/Button';
import { Input } from '@/shared/Input';
import { useSetPortConfig } from '@/api/queries';
import { buildPortConfigPatch, currentMode, parseTagged, type PortMode } from '@/lib/portConfigPatch';
import { pushToast } from '@/store/toast';
import { cn } from '@/lib/cn';
import type { Port } from '@/models';

interface PortConfigEditorProps {
  deviceId: string;
  port: Port;
}

type Mode = PortMode;

/**
 * Admin-only DIRECT device write of port tunables: port-mode, native/untagged
 * VLAN, tagged VLANs, MTU and admin enable/disable. Only changed fields are
 * sent; the backend commits immediately (no approval gate).
 */
export function PortConfigEditor({ deviceId, port }: PortConfigEditorProps) {
  const setConfig = useSetPortConfig(deviceId);

  const [mode, setMode] = useState<Mode>(currentMode(port));
  const [native, setNative] = useState(port.untagged_vlan);
  const [taggedText, setTaggedText] = useState(port.tagged_vlans.join(', '));
  const [mtu, setMtu] = useState(port.mtu);
  const [enabled, setEnabled] = useState(port.admin_up);

  // Re-seed when the selected port changes (panel reused across ports).
  useEffect(() => {
    setMode(port.tagged_vlans.length > 0 ? 'trunk' : 'access');
    setNative(port.untagged_vlan);
    setTaggedText(port.tagged_vlans.join(', '));
    setMtu(port.mtu);
    setEnabled(port.admin_up);
  }, [port]);

  const tagged = parseTagged(taggedText);
  const patch = buildPortConfigPatch(port, { mode, native, tagged, mtu, enabled });
  const dirty = Object.keys(patch).length > 0;

  const apply = () => {
    setConfig.mutate(
      { portName: port.name, patch },
      {
        onSuccess: () => pushToast({ kind: 'success', message: 'Port config written to device.' }),
        onError: (e: unknown) =>
          pushToast({ kind: 'error', message: e instanceof Error ? e.message : 'Write failed.' }),
      },
    );
  };

  return (
    <div className="space-y-3 text-xs">
      <Row label="Port mode">
        <div className="flex gap-1">
          {(['access', 'trunk'] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={cn(
                'rounded-md border px-2.5 py-1 text-[11px] capitalize transition',
                mode === m
                  ? 'border-accent bg-accent/10 text-accent'
                  : 'border-border text-fg-muted hover:border-border-strong hover:text-fg',
              )}
            >
              {m}
            </button>
          ))}
        </div>
      </Row>

      <Row label={mode === 'trunk' ? 'Native VLAN' : 'Access VLAN'}>
        <Input
          type="number"
          value={native}
          onChange={(e) => setNative(parseInt(e.target.value, 10) || 0)}
          className="h-7 w-24 text-[11px]"
          aria-label="Native or access VLAN"
        />
      </Row>

      {mode === 'trunk' && (
        <Row label="Tagged VLANs">
          <Input
            value={taggedText}
            onChange={(e) => setTaggedText(e.target.value)}
            placeholder="100, 200, 300"
            className="h-7 flex-1 text-[11px]"
            aria-label="Tagged VLANs (comma-separated)"
          />
        </Row>
      )}

      <Row label="MTU">
        <Input
          type="number"
          value={mtu}
          onChange={(e) => setMtu(parseInt(e.target.value, 10) || 0)}
          className="h-7 w-24 text-[11px]"
          aria-label="MTU"
        />
      </Row>

      <Row label="Admin state">
        <button
          type="button"
          onClick={() => setEnabled((v) => !v)}
          className={cn(
            'flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] transition',
            enabled
              ? 'border-success/40 bg-success/10 text-success'
              : 'border-danger/40 bg-danger/10 text-danger',
          )}
        >
          <Power size={11} />
          {enabled ? 'Enabled' : 'Disabled'}
        </button>
      </Row>

      <div className="flex items-center gap-2 pt-1">
        <Button
          size="sm"
          leftIcon={<Save size={12} />}
          disabled={!dirty || setConfig.isPending}
          onClick={apply}
        >
          {setConfig.isPending ? 'Writing…' : 'Apply to device'}
        </Button>
        {dirty && <span className="text-[10px] text-fg-subtle">Unsaved changes</span>}
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-24 shrink-0 text-[11px] uppercase tracking-wider text-fg-subtle">
        {label}
      </span>
      {children}
    </div>
  );
}
