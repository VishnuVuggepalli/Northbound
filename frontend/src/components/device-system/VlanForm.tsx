import { useState } from 'react';
import { useCreateVlanRequest } from '@/api/queries';
import { Input } from '@/shared/Input';
import { Button } from '@/shared/Button';
import { pushToast } from '@/store/toast';
import { FormField, FormShell } from './FormShell';
import { filingErrorToast, type VlanFormInitial } from './support';

interface VlanFormProps {
  deviceId: string;
  initial: VlanFormInitial;
  onClose: () => void;
}

/** Inline "request VLAN create/update" form — files a change request. */
export function VlanForm({ deviceId, initial, onClose }: VlanFormProps) {
  const createVlan = useCreateVlanRequest();
  const [vid, setVid] = useState(initial.vid);
  const [name, setName] = useState(initial.name);
  const [desc, setDesc] = useState(initial.desc);

  return (
    <FormShell
      onSubmit={(e) => {
        e.preventDefault();
        const parsed = Number.parseInt(vid, 10);
        if (!Number.isFinite(parsed) || parsed < 1 || parsed > 4094) {
          pushToast({ kind: 'error', title: 'VLAN id must be 1–4094' });
          return;
        }
        createVlan.mutate(
          {
            device_id: deviceId,
            action: 'create',
            vlan_id: parsed,
            name: name || undefined,
            description: desc || undefined,
          },
          {
            onSuccess: () => {
              pushToast({
                kind: 'success',
                title: 'VLAN change requested',
                message: `Create VLAN ${parsed} — pending approval`,
              });
              onClose();
            },
            onError: filingErrorToast,
          },
        );
      }}
    >
      <FormField label="VLAN id">
        <Input
          type="number"
          min={1}
          max={4094}
          value={vid}
          onChange={(e) => setVid(e.target.value)}
          className="h-8 w-28"
          autoFocus
          required
        />
      </FormField>
      <FormField label="Name (optional)">
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="h-8 w-40"
          placeholder="e.g. web-tier"
        />
      </FormField>
      <FormField label="Description (optional)">
        <Input
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          className="h-8 w-48"
          placeholder="free text"
        />
      </FormField>
      <Button type="submit" kind="primary" size="sm" disabled={createVlan.isPending}>
        {createVlan.isPending ? 'Filing…' : 'Request VLAN'}
      </Button>
      <Button type="button" kind="ghost" size="sm" onClick={onClose}>
        Cancel
      </Button>
      <span className="basis-full text-[11px] text-fg-subtle">
        Files a change request — an admin approves &amp; applies it (commit-confirm).
      </span>
    </FormShell>
  );
}
