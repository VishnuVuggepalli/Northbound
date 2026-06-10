import { useState } from 'react';
import { useCreateL3Request } from '@/api/queries';
import { Input } from '@/shared/Input';
import { Button } from '@/shared/Button';
import { pushToast } from '@/store/toast';
import { FormField, FormShell } from './FormShell';
import { filingErrorToast, type L3FormInitial } from './support';

interface L3FormProps {
  deviceId: string;
  initial: L3FormInitial;
  onClose: () => void;
}

/** Inline "request L3 interface" form (SVI or loopback) — files a change request. */
export function L3Form({ deviceId, initial, onClose }: L3FormProps) {
  const createL3 = useCreateL3Request();
  const [kind, setKind] = useState(initial.kind);
  const [vid, setVid] = useState(initial.vid);
  const [name, setName] = useState(initial.name);
  const [ip, setIp] = useState(initial.ip);
  const [mtu, setMtu] = useState(initial.mtu);
  const [vrf, setVrf] = useState(initial.vrf);

  return (
    <FormShell
      onSubmit={(e) => {
        e.preventDefault();
        if (!ip.trim()) {
          pushToast({ kind: 'error', title: 'IPv4 (CIDR) is required' });
          return;
        }
        const parsedVid = Number.parseInt(vid, 10);
        if (kind === 'svi' && !Number.isFinite(parsedVid)) {
          pushToast({ kind: 'error', title: 'SVI needs a VLAN id' });
          return;
        }
        const parsedMtu = Number.parseInt(mtu, 10);
        createL3.mutate(
          {
            device_id: deviceId,
            action: 'create',
            kind,
            vlan_id: kind === 'svi' ? parsedVid : undefined,
            name: kind === 'loopback' ? name || undefined : undefined,
            ipv4: ip.trim(),
            mtu: Number.isFinite(parsedMtu) ? parsedMtu : undefined,
            vrf: vrf.trim() || undefined,
          },
          {
            onSuccess: () => {
              pushToast({
                kind: 'success',
                title: 'L3 change requested',
                message: `Create ${kind} — pending approval`,
              });
              onClose();
            },
            onError: filingErrorToast,
          },
        );
      }}
    >
      <FormField label="Kind">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as 'svi' | 'loopback')}
          className="h-8 rounded-md border border-border bg-bg-elev-1 px-2 text-xs text-fg"
        >
          <option value="svi">SVI (VLAN interface)</option>
          <option value="loopback">Loopback</option>
        </select>
      </FormField>
      {kind === 'svi' ? (
        <FormField label="VLAN id">
          <Input
            type="number"
            min={1}
            max={4094}
            value={vid}
            onChange={(e) => setVid(e.target.value)}
            className="h-8 w-28"
            required
          />
        </FormField>
      ) : (
        <FormField label="Name">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="h-8 w-32"
            placeholder="lo0"
            required
          />
        </FormField>
      )}
      <FormField label="IPv4 (CIDR)">
        <Input
          value={ip}
          onChange={(e) => setIp(e.target.value)}
          className="h-8 w-44"
          placeholder="10.10.250.2/16"
          required
        />
      </FormField>
      <FormField label="MTU (optional)">
        <Input
          type="number"
          min={64}
          max={16360}
          value={mtu}
          onChange={(e) => setMtu(e.target.value)}
          className="h-8 w-24"
          placeholder="1500"
        />
      </FormField>
      <FormField label="VRF (optional)">
        <Input
          value={vrf}
          onChange={(e) => setVrf(e.target.value)}
          className="h-8 w-32"
          placeholder="must already exist"
        />
      </FormField>
      <Button type="submit" kind="primary" size="sm" disabled={createL3.isPending}>
        {createL3.isPending ? 'Filing…' : 'Request L3'}
      </Button>
      <Button type="button" kind="ghost" size="sm" onClick={onClose}>
        Cancel
      </Button>
      <span className="basis-full text-[11px] text-fg-subtle">
        Files a change request — admin approves &amp; applies (commit-confirm).
      </span>
    </FormShell>
  );
}
