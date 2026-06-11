import { cn } from '@/lib/cn';

interface SkeletonProps {
  className?: string;
}

/**
 * A shimmering placeholder block for loading states, so "loading" reads
 * differently from "empty". Uses a design-token surface and `animate-pulse`
 * (globally neutralized under `prefers-reduced-motion`). Decorative → aria-hidden.
 */
function Skeleton({ className }: SkeletonProps) {
  return <div className={cn('animate-pulse rounded bg-bg-elev-2', className)} aria-hidden />;
}

interface SkeletonListProps {
  rows?: number;
  className?: string;
  rowClassName?: string;
}

/** A vertical stack of skeleton rows for list placeholders. */
export function SkeletonList({ rows = 4, className, rowClassName }: SkeletonListProps) {
  return (
    <div className={cn('flex flex-col gap-2', className)} aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={cn('h-8 w-full', rowClassName)} />
      ))}
    </div>
  );
}
