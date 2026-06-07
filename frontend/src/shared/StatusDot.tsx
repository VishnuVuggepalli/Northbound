import { cn } from '@/lib/cn';

type DotState = 'up' | 'down' | 'disabled' | 'off' | 'pending';

interface StatusDotProps {
  state: DotState;
  size?: number;
  pulse?: boolean;
  className?: string;
  /**
   * Accessible status text. Pass it where the dot is the ONLY status indicator
   * (e.g. the sidebar) so state isn't conveyed by color alone — it becomes a
   * labelled `img` (announced by screen readers) with a hover tooltip. Omit it
   * where adjacent text already names the status (the dot stays decorative).
   */
  label?: string;
}

const COLOR: Record<DotState, string> = {
  up: 'bg-success',
  down: 'bg-danger/80',
  disabled: 'bg-warn',
  off: 'bg-fg-subtle/60',
  pending: 'bg-warn',
};

export function StatusDot({ state, size = 8, pulse = false, className, label }: StatusDotProps) {
  return (
    <span
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      title={label}
      className={cn(
        'inline-block shrink-0 rounded-full',
        COLOR[state],
        pulse && 'animate-pulse-soft',
        className,
      )}
      style={{ width: size, height: size, boxShadow: '0 0 8px -2px currentColor' }}
    />
  );
}
