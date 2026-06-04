import { cn } from '@/lib/cn';
import { useLiveStore, type LiveStatus } from '@/store/live';

const PRESENTATION: Record<LiveStatus, { dot: string; label: string; pulse: boolean }> = {
  open: { dot: 'bg-success', label: 'Live', pulse: false },
  connecting: { dot: 'bg-warn', label: 'Connecting…', pulse: true },
  closed: { dot: 'bg-fg-muted', label: 'Offline', pulse: false },
};

/**
 * Small status pill showing the SSE live-stream connection (F157). Lets users
 * see that device/port updates are flowing in real time rather than wondering
 * whether the page is stale. Status is published by `useEventStream`.
 */
export function LiveIndicator() {
  const status = useLiveStore((s) => s.status);
  const { dot, label, pulse } = PRESENTATION[status];
  return (
    <span
      className="flex h-9 items-center gap-1.5 rounded-md px-2 text-xs text-fg-muted"
      title={`Live updates: ${label}`}
      aria-label={`Live updates ${label}`}
      role="status"
    >
      <span className={cn('h-2 w-2 rounded-full', dot, pulse && 'animate-pulse')} aria-hidden />
      <span className="hidden sm:inline">{label}</span>
    </span>
  );
}
