import { useState } from 'react';
import { useCreateOspfRequest } from '@/api/queries';
import { Input } from '@/shared/Input';
import { Button } from '@/shared/Button';
import { pushToast } from '@/store/toast';
import { isPlausibleArea, isPlausibleIp } from '@/lib/format';
import { FormField, FormShell } from './FormShell';
import { filingErrorToast, type OspfFormInitial } from './support';

interface OspfFormProps {
  deviceId: string;
  initial: OspfFormInitial;
  onClose: () => void;
}

/** Inline "request OSPF change" form (interface → area, or router-id). */
export function OspfForm({ deviceId, initial, onClose }: OspfFormProps) {
  const createOspf = useCreateOspfRequest();
  const [target, setTarget] = useState(initial.target);
  const [iface, setIface] = useState(initial.iface);
  const [area, setArea] = useState(initial.area);
  const [routerId, setRouterId] = useState(initial.routerId);
  const [cost, setCost] = useState(initial.cost);

  const routerIdInvalid =
    target === 'router-id' && routerId.trim().length > 0 && !isPlausibleIp(routerId);
  const areaInvalid =
    target === 'interface' && area.trim().length > 0 && !isPlausibleArea(area);
  const parsedCostNum = Number.parseInt(cost, 10);
  const costInvalid =
    cost.trim().length > 0 && (parsedCostNum < 1 || parsedCostNum > 65535);
  const blockSubmit = routerIdInvalid || areaInvalid || costInvalid;

  return (
    <FormShell
      tone="warn"
      onSubmit={(e) => {
        e.preventDefault();
        const parsedCost = Number.parseInt(cost, 10);
        if (target === 'router-id' && !routerId.trim()) {
          pushToast({ kind: 'error', title: 'router-id required' });
          return;
        }
        if (target === 'interface' && (!iface.trim() || !area.trim())) {
          pushToast({ kind: 'error', title: 'interface + area required' });
          return;
        }
        if (blockSubmit) return;
        createOspf.mutate(
          {
            device_id: deviceId,
            action: 'set',
            target,
            router_id: target === 'router-id' ? routerId.trim() : undefined,
            interface: target === 'interface' ? iface.trim() : undefined,
            area: target === 'interface' ? area.trim() : undefined,
            cost: target === 'interface' && Number.isFinite(parsedCost) ? parsedCost : undefined,
          },
          {
            onSuccess: () => {
              pushToast({
                kind: 'success',
                title: 'OSPF change requested',
                message: 'pending approval',
              });
              onClose();
            },
            onError: filingErrorToast,
          },
        );
      }}
    >
      <FormField label="OSPF target">
        <select
          value={target}
          onChange={(e) => setTarget(e.target.value as 'interface' | 'router-id')}
          className="h-8 rounded-md border border-border bg-bg-elev-1 px-2 text-xs text-fg"
        >
          <option value="interface">Interface → area</option>
          <option value="router-id">Router ID</option>
        </select>
      </FormField>
      {target === 'interface' ? (
        <>
          <FormField label="Interface">
            <Input
              value={iface}
              onChange={(e) => setIface(e.target.value)}
              className="h-8 w-32"
              placeholder="vlan1010"
              required
            />
          </FormField>
          <FormField label="Area">
            <Input
              value={area}
              onChange={(e) => setArea(e.target.value)}
              className="h-8 w-28"
              placeholder="0.0.0.0"
              required
              aria-invalid={areaInvalid}
              aria-describedby={areaInvalid ? 'ospf-area-error' : undefined}
            />
            {areaInvalid && (
              <span id="ospf-area-error" role="alert" className="mt-1 block text-xs text-danger">
                Area must be an integer or dotted-quad
              </span>
            )}
          </FormField>
          <FormField label="Cost (optional)">
            <Input
              type="number"
              min={1}
              max={65535}
              value={cost}
              onChange={(e) => setCost(e.target.value)}
              className="h-8 w-24"
              aria-invalid={costInvalid}
              aria-describedby={costInvalid ? 'ospf-cost-error' : undefined}
            />
            {costInvalid && (
              <span id="ospf-cost-error" role="alert" className="mt-1 block text-xs text-danger">
                Cost must be 1–65535
              </span>
            )}
          </FormField>
        </>
      ) : (
        <FormField label="Router ID">
          <Input
            value={routerId}
            onChange={(e) => setRouterId(e.target.value)}
            className="h-8 w-36"
            placeholder="10.10.250.2"
            required
            aria-invalid={routerIdInvalid}
            aria-describedby={routerIdInvalid ? 'ospf-routerid-error' : undefined}
          />
          {routerIdInvalid && (
            <span id="ospf-routerid-error" role="alert" className="mt-1 block text-xs text-danger">
              Not a valid IPv4 address
            </span>
          )}
        </FormField>
      )}
      <Button
        type="submit"
        kind="primary"
        size="sm"
        disabled={createOspf.isPending || blockSubmit}
      >
        {createOspf.isPending ? 'Filing…' : 'Request OSPF'}
      </Button>
      <Button type="button" kind="ghost" size="sm" onClick={onClose}>
        Cancel
      </Button>
      <span className="basis-full text-[11px] text-fg-subtle">
        Filing only — OSPF applies touch live routing; an admin reviews before apply.
      </span>
    </FormShell>
  );
}
