import { useEffect, useMemo, useRef, useState } from 'react';
import { Server, X } from 'lucide-react';
import { Kbd } from '@/shared/Kbd';
import { Input } from '@/shared/Input';
import { cn } from '@/lib/cn';
import { PortCard } from './PortCard';
import { deriveFaceplate, type ConnectorType } from '@/lib/faceplate';
import type { ThemeMode } from '@/lib/palette';
import type { ChangeRequest, Device, Port } from '@/models';

interface PortStripProps {
  device: Device;
  ports: Port[];
  selected: string | null;
  requests: ChangeRequest[];
  theme: ThemeMode;
  onSelect: (name: string) => void;
}

export function PortStrip({
  device,
  ports,
  selected,
  requests,
  theme,
  onSelect,
}: PortStripProps) {
  const wrapRef = useRef<HTMLDivElement>(null);

  // --- filters (per device): BMC presence, BMC IP / name / description text,
  //     untagged VLAN, tagged-VLAN membership. ----------------------------------
  const [query, setQuery] = useState('');
  const [bmcOnly, setBmcOnly] = useState(false);
  const [untagged, setUntagged] = useState('');
  const [tagged, setTagged] = useState('');

  // Distinct VLANs actually present on this device, for the dropdowns.
  const untaggedOptions = useMemo(
    () => [...new Set(ports.map((p) => p.untagged_vlan).filter((v) => v > 0))].sort((a, b) => a - b),
    [ports],
  );
  const taggedOptions = useMemo(
    () => [...new Set(ports.flatMap((p) => p.tagged_vlans))].sort((a, b) => a - b),
    [ports],
  );

  const filterActive = !!(query.trim() || bmcOnly || untagged || tagged);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const uv = untagged ? Number(untagged) : null;
    const tv = tagged ? Number(tagged) : null;
    return ports.filter((p) => {
      if (bmcOnly && !p.bmc_ip) return false;
      if (uv !== null && p.untagged_vlan !== uv) return false;
      if (tv !== null && !p.tagged_vlans.includes(tv)) return false;
      if (
        q &&
        !p.name.toLowerCase().includes(q) &&
        !p.description.toLowerCase().includes(q) &&
        !p.bmc_ip.toLowerCase().includes(q)
      ) {
        return false;
      }
      return true;
    });
  }, [ports, query, bmcOnly, untagged, tagged]);

  // Connector type per port, resolved through the SAME derivation the faceplate
  // uses (lib/faceplate) rather than classified per card. Classification needs
  // the whole group: `speed_mbps` is the negotiated rate, so a down QSFP
  // reports null and would render as a plain SFP if judged alone.
  const connectorByPort = useMemo(() => {
    const map = new Map<string, ConnectorType>();
    for (const group of deriveFaceplate(ports).groups) {
      for (const slot of group.slots) {
        for (const port of slot.ports) map.set(port.name, group.connector);
      }
    }
    return map;
  }, [ports]);

  // Auto-scroll the selected port into view (used by `j`/`k` shortcuts).
  useEffect(() => {
    if (!selected) return;
    const el = wrapRef.current?.querySelector<HTMLElement>(
      `[data-port="${CSS.escape(selected)}"]`,
    );
    el?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  }, [selected]);

  const counts = {
    up: filtered.filter((p) => p.state === 'up').length,
    down: filtered.filter((p) => p.state === 'down').length,
    disabled: filtered.filter((p) => p.state === 'disabled').length,
  };
  const hasBmc = ports.some((p) => p.bmc_ip);

  const clearFilters = () => {
    setQuery('');
    setBmcOnly(false);
    setUntagged('');
    setTagged('');
  };

  const selectCls =
    'h-7 rounded-md border border-border bg-bg-elev-1 px-1.5 text-xs text-fg disabled:opacity-40';

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 text-xs">
        <div className="flex items-center gap-3 text-fg-muted">
          <span className="nb-mono font-semibold text-fg">
            {filterActive ? `${filtered.length} / ${ports.length}` : ports.length} ports
          </span>
          <Legend label={`${counts.up} up`} color="bg-success" />
          <Legend label={`${counts.down} down`} color="bg-danger/70" />
          <Legend label={`${counts.disabled} disabled`} color="bg-warn" />
        </div>
        <div className="flex items-center gap-1.5 text-fg-muted">
          <Kbd>j</Kbd>
          <Kbd>k</Kbd>
          <span>to move</span>
          <span>·</span>
          <Kbd>r</Kbd>
          <span>to request</span>
        </div>
      </header>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-2 text-xs">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by BMC IP, name, description…"
          className="h-7 w-60 text-xs"
        />
        <button
          type="button"
          onClick={() => setBmcOnly((v) => !v)}
          disabled={!hasBmc}
          title={hasBmc ? 'Show only ports with a BMC IP' : 'No BMC IPs on this device'}
          className={cn(
            'flex items-center gap-1 rounded-md border px-2 py-1 transition-colors disabled:opacity-40',
            bmcOnly
              ? 'border-accent bg-accent-soft text-accent'
              : 'border-border bg-bg-elev-1 text-fg-muted hover:text-fg',
          )}
        >
          <Server size={11} />
          Has BMC
        </button>
        <label className="flex items-center gap-1 text-fg-muted">
          Untagged
          <select
            value={untagged}
            onChange={(e) => setUntagged(e.target.value)}
            disabled={untaggedOptions.length === 0}
            className={selectCls}
          >
            <option value="">any</option>
            {untaggedOptions.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 text-fg-muted">
          Tagged
          <select
            value={tagged}
            onChange={(e) => setTagged(e.target.value)}
            disabled={taggedOptions.length === 0}
            className={selectCls}
          >
            <option value="">any</option>
            {taggedOptions.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        {filterActive && (
          <button
            type="button"
            onClick={clearFilters}
            className="flex items-center gap-1 rounded-md border border-border bg-bg-elev-1 px-2 py-1 text-fg-muted hover:text-fg"
          >
            <X size={11} />
            Clear
          </button>
        )}
      </div>

      <div
        ref={wrapRef}
        className="nb-scroll flex-1 overflow-x-auto overflow-y-hidden border-t border-border px-4 py-3"
      >
        {filtered.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-fg-muted">
            No ports match the current filters.
          </div>
        ) : (
          <div className="flex gap-2 pr-4">
            {filtered.map((p) => (
              <PortCard
                key={p.name}
                port={p}
                connector={connectorByPort.get(p.name) ?? 'unknown'}
                theme={theme}
                selected={selected === p.name}
                pendingRequests={requests.filter(
                  (r) =>
                    r.device_id === device.id &&
                    r.port_name === p.name &&
                    r.status === 'pending',
                )}
                onClick={() => onSelect(p.name)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Legend({ label, color }: { label: string; color: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${color}`} />
      <span>{label}</span>
    </span>
  );
}
