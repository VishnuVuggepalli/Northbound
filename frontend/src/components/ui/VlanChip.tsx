import { X } from 'lucide-react';
import { vlanColor, vlanColorMuted, vlanZone, type ThemeMode } from '@/lib/vlan';
import { cn } from '@/lib/cn';

interface VlanChipProps {
  vlan: number | null | undefined;
  theme: ThemeMode;
  large?: boolean;
  selected?: boolean;
  onRemove?: () => void;
  className?: string;
}

/**
 * Renders a VLAN chip with the deterministic VLAN color (see `lib/vlan.ts`).
 * Same VLAN number always renders the same hue across:
 *  - 3D port LED stripe
 *  - 2D port card
 *  - request form
 *  - diff view
 */
export function VlanChip({
  vlan,
  theme,
  large,
  selected,
  onRemove,
  className,
}: VlanChipProps) {
  const color = vlanColor(vlan, theme);
  const muted = vlanColorMuted(vlan, theme);
  const zone = vlanZone(vlan ?? null);
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 font-mono leading-none',
        'transition-colors',
        large ? 'h-8 px-2.5 text-sm' : 'h-6 text-[11px]',
        selected && 'ring-2 ring-offset-1 ring-offset-bg',
        className,
      )}
      style={{
        background: muted,
        borderColor: color,
        color,
        // @ts-expect-error CSS custom property
        '--tw-ring-color': color,
      }}
      title={zone ? `VLAN ${vlan} · ${zone.name}` : `VLAN ${vlan ?? '—'}`}
    >
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: color }}
      />
      <span className="font-semibold">{vlan ?? '—'}</span>
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="rounded-sm p-0.5 hover:bg-black/20"
          aria-label="Remove VLAN"
        >
          <X size={10} />
        </button>
      )}
    </span>
  );
}
