import type { FormEventHandler, ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface FormShellProps {
  /** Visual emphasis: accent (routine writes) or warn (touches live routing). */
  tone?: 'accent' | 'warn';
  onSubmit: FormEventHandler<HTMLFormElement>;
  children: ReactNode;
}

/** Inline change-request form container shared by the device-system forms. */
export function FormShell({ tone = 'accent', onSubmit, children }: FormShellProps) {
  return (
    <form
      className={cn(
        'mb-3 flex flex-wrap items-end gap-2 rounded-md border p-3',
        tone === 'warn' ? 'border-warn/40 bg-warn/5' : 'border-accent/30 bg-accent-soft',
      )}
      onSubmit={onSubmit}
    >
      {children}
    </form>
  );
}

/** Labeled field wrapper matching the inline-form label style. */
export function FormField({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-fg-muted">
      {label}
      {children}
    </label>
  );
}

