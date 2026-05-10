import { cn } from '@/lib/cn';

type DotState = 'up' | 'down' | 'disabled' | 'off' | 'pending';

interface StatusDotProps {
  state: DotState;
  size?: number;
  pulse?: boolean;
  className?: string;
}

const COLOR: Record<DotState, string> = {
  up: 'bg-success',
  down: 'bg-danger/80',
  disabled: 'bg-warn',
  off: 'bg-fg-subtle/60',
  pending: 'bg-warn',
};

export function StatusDot({ state, size = 8, pulse = false, className }: StatusDotProps) {
  return (
    <span
      aria-hidden
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
