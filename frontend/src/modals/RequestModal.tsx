import { useEffect, useState } from 'react';
import { Send } from 'lucide-react';
import { Modal } from '@/modals/Modal';
import { Button } from '@/shared/Button';
import { Input, Textarea } from '@/shared/Input';
import { vlanColor, vlanColorMuted } from '@/lib/vlan';
import { isPlausibleIp } from '@/lib/format';
import type { ThemeMode } from '@/lib/palette';
import type { Device, Port, RequestedChanges } from '@/models';
import { cn } from '@/lib/cn';
import { useAuthStore } from '@/store/auth';

interface RequestModalProps {
  open: boolean;
  device: Device | null;
  port: Port | null;
  theme: ThemeMode;
  vlanOptions: readonly number[];
  onClose: () => void;
  onSubmit: (input: { changes: RequestedChanges; reason: string }) => void;
  submitting?: boolean;
}

export function RequestModal({
  open,
  device,
  port,
  theme,
  vlanOptions,
  onClose,
  onSubmit,
  submitting,
}: RequestModalProps) {
  const [untagged, setUntagged] = useState<number>(port?.untagged_vlan ?? 100);
  const [tagged, setTagged] = useState<number[]>(port?.tagged_vlans ?? []);
  const [host, setHost] = useState(port?.host_model ?? '');
  const [bmc, setBmc] = useState(port?.bmc_ip ?? '');
  const [notes, setNotes] = useState(port?.notes ?? '');
  const [reason, setReason] = useState('');
  const isAdmin = useAuthStore((s) => s.user?.role) === 'admin';

  useEffect(() => {
    if (open && port) {
      setUntagged(port.untagged_vlan);
      setTagged(port.tagged_vlans);
      setHost(port.host_model);
      setBmc(port.bmc_ip);
      setNotes(port.notes);
      setReason('');
    }
  }, [open, port]);

  if (!open || !device || !port) return null;

  const ipValid = !bmc || isPlausibleIp(bmc);
  const valid = !!reason.trim() && ipValid && !!untagged;

  const handleSubmit = () => {
    if (!valid) return;
    onSubmit({
      changes: {
        untagged_vlan: untagged,
        tagged_vlans: tagged,
        host_model: host,
        bmc_ip: bmc,
        notes,
      },
      reason: reason.trim(),
    });
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Request port change"
      subtitle={`${device.name} · ${port.name}`}
      width={620}
      footer={
        <>
          <Button kind="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            kind="primary"
            leftIcon={<Send size={14} />}
            disabled={!valid || submitting}
            onClick={handleSubmit}
          >
            {submitting ? 'Submitting…' : 'Submit request'}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <Field label="Untagged VLAN">
          <div className="flex items-start gap-3">
            <Input
              type="number"
              value={untagged}
              onChange={(e) => setUntagged(parseInt(e.target.value) || 0)}
              className="w-28"
            />
            <div className="flex flex-wrap gap-1.5">
              {vlanOptions.map((v) => (
                <ChipButton
                  key={v}
                  vlan={v}
                  theme={theme}
                  selected={untagged === v}
                  onClick={() => setUntagged(v)}
                />
              ))}
            </div>
          </div>
        </Field>

        <Field label="Tagged VLANs (trunk)">
          <div className="flex flex-wrap gap-1.5">
            {vlanOptions
              .filter((v) => v !== untagged)
              .map((v) => {
                const on = tagged.includes(v);
                return (
                  <ChipButton
                    key={v}
                    vlan={v}
                    theme={theme}
                    selected={on}
                    onClick={() =>
                      setTagged((current) =>
                        on ? current.filter((x) => x !== v) : [...current, v],
                      )
                    }
                  />
                );
              })}
          </div>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Host model">
            <Input value={host} onChange={(e) => setHost(e.target.value)} placeholder="e.g. Dell R740" />
          </Field>
          <Field label="BMC IP">
            <Input
              value={bmc}
              onChange={(e) => setBmc(e.target.value)}
              placeholder="10.0.0.55"
              className="nb-mono"
              aria-invalid={!ipValid}
              aria-describedby={!ipValid ? 'request-bmc-ip-error' : undefined}
              autoComplete="off"
              inputMode="decimal"
            />
            {!ipValid && (
              <span
                id="request-bmc-ip-error"
                role="alert"
                className="mt-1 block text-xs text-danger"
              >
                Use dotted-quad format (e.g. 10.0.0.55).
              </span>
            )}
          </Field>
        </div>

        {isAdmin && (
          <Field label="Notes (optional)">
            <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
        )}

        <Field label="Reason for change (required)">
          <Textarea
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="What's this for? Tickets, dates, who's affected."
          />
        </Field>
      </div>
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wider text-fg-subtle">
        {label}
      </span>
      {children}
    </label>
  );
}

interface ChipButtonProps {
  vlan: number;
  selected: boolean;
  theme: ThemeMode;
  onClick: () => void;
}

function ChipButton({ vlan, selected, theme, onClick }: ChipButtonProps) {
  const color = vlanColor(vlan, theme);
  const muted = vlanColorMuted(vlan, theme);
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'nb-mono flex h-7 items-center gap-1.5 rounded-md border px-2 text-[11px] transition',
        selected
          ? 'shadow-[0_0_0_1px_currentColor_inset]'
          : 'border-border text-fg-muted hover:border-border-strong hover:text-fg',
      )}
      style={
        selected
          ? { background: muted, borderColor: color, color }
          : undefined
      }
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      <span className="font-semibold">{vlan}</span>
    </button>
  );
}
