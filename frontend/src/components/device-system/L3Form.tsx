import { useState } from 'react';
import { useCreateL3Request } from '@/api/queries';
import { Input } from '@/shared/Input';
import { Button } from '@/shared/Button';
import { pushToast } from '@/store/toast';
import { isPlausibleCidr } from '@/lib/format';
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

  const ipInvalid = ip.trim().length > 0 && !isPlausibleCidr(ip);
  const parsedVidNum = Number.parseInt(vid, 10);
  const vidInvalid =
    kind === 'svi' && vid.trim().length > 0 && (parsedVidNum < 1 || parsedVidNum > 4094);
  const parsedMtuNum = Number.parseInt(mtu, 10);
  const mtuInvalid =
    mtu.trim().length > 0 && (parsedMtuNum < 64 || parsedMtuNum > 16360);
  const blockSubmit = ipInvalid || vidInvalid || mtuInvalid;

  return (
    <FormShell
      onSubmit={(e) => {
        e.preventDefault();
        if (!ip.trim()) {
          pushToast({ kind: 'error', title: 'IPv4 (CIDR) is required' });
          return;
        }
        if (blockSubmit) return;
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
            aria-invalid={vidInvalid}
            aria-describedby={vidInvalid ? 'l3-vid-error' : undefined}
          />
          {vidInvalid && (
            <span id="l3-vid-error" role="alert" className="mt-1 block text-xs text-danger">
              VLAN id must be 1–4094
            </span>
          )}
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
          aria-invalid={ipInvalid}
          aria-describedby={ipInvalid ? 'l3-ip-error' : undefined}
        />
        {ipInvalid && (
          <span id="l3-ip-error" role="alert" className="mt-1 block text-xs text-danger">
            Not a valid IP/CIDR
          </span>
        )}
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
          aria-invalid={mtuInvalid}
          aria-describedby={mtuInvalid ? 'l3-mtu-error' : undefined}
        />
        {mtuInvalid && (
          <span id="l3-mtu-error" role="alert" className="mt-1 block text-xs text-danger">
            MTU must be 64–16360
          </span>
        )}
      </FormField>
      <FormField label="VRF (optional)">
        <Input
          value={vrf}
          onChange={(e) => setVrf(e.target.value)}
          className="h-8 w-32"
          placeholder="must already exist"
        />
      </FormField>
      <Button
        type="submit"
        kind="primary"
        size="sm"
        disabled={createL3.isPending || blockSubmit}
      >
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
