import { useState } from 'react';
import { useCreateVrfRequest } from '@/api/queries';
import { Input } from '@/shared/Input';
import { Button } from '@/shared/Button';
import { pushToast } from '@/store/toast';
import { FormField, FormShell } from './FormShell';
import { filingErrorToast } from './support';

interface VrfFormProps {
  deviceId: string;
  onClose: () => void;
}

/** Inline "request VRF create" form — files a change request. */
export function VrfForm({ deviceId, onClose }: VrfFormProps) {
  const createVrf = useCreateVrfRequest();
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');

  return (
    <FormShell
      onSubmit={(e) => {
        e.preventDefault();
        if (!name.trim()) {
          pushToast({ kind: 'error', title: 'VRF name is required' });
          return;
        }
        createVrf.mutate(
          {
            device_id: deviceId,
            action: 'create',
            name: name.trim(),
            description: desc || undefined,
          },
          {
            onSuccess: () => {
              pushToast({
                kind: 'success',
                title: 'VRF change requested',
                message: `Create VRF ${name.trim()} — pending approval`,
              });
              onClose();
            },
            onError: filingErrorToast,
          },
        );
      }}
    >
      <FormField label="VRF name">
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="h-8 w-40"
          placeholder="tenant-a"
          autoFocus
          required
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
      <Button type="submit" kind="primary" size="sm" disabled={createVrf.isPending}>
        {createVrf.isPending ? 'Filing…' : 'Request VRF'}
      </Button>
      <Button type="button" kind="ghost" size="sm" onClick={onClose}>
        Cancel
      </Button>
    </FormShell>
  );
}
