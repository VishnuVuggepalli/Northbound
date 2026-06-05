import type { HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

type Variant = 'default' | 'accent' | 'success' | 'warn' | 'danger' | 'muted';

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: Variant;
}

const VARIANTS: Record<Variant, string> = {
  default: 'bg-bg-elev-2 text-fg border-border',
  accent: 'bg-accent-soft text-accent border-accent/40',
  success: 'bg-success/15 text-success border-success/30',
  warn: 'bg-warn/15 text-warn border-warn/30',
  danger: 'bg-danger/15 text-danger border-danger/30',
  muted: 'bg-bg-elev-2 text-fg-muted border-border',
};

export function Badge({ variant = 'default', className, ...rest }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider',
        VARIANTS[variant],
        className,
      )}
      {...rest}
    />
  );
}
