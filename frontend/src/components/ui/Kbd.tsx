import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn('nb-kbd', className)}>{children}</span>;
}
