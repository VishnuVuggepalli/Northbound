import type { ReactNode } from 'react';

interface KVProps {
  label: string;
  children: ReactNode;
  /**
   * `row` (default): a `<dt>/<dd>` fragment for use inside a `<dl>` grid
   * (label left, value right). `stacked`: a self-contained block with the
   * label above the value.
   */
  variant?: 'row' | 'stacked';
}

/** Shared key/value display row. The one KV used across the app. */
export function KV({ label, children, variant = 'row' }: KVProps) {
  if (variant === 'stacked') {
    return (
      <div>
        <div className="mb-0.5 text-[10px] uppercase tracking-wider text-fg-subtle">{label}</div>
        <div className="text-sm text-fg">{children}</div>
      </div>
    );
  }
  return (
    <>
      <dt className="text-[11px] uppercase tracking-wider text-fg-subtle">{label}</dt>
      <dd className="text-fg">{children}</dd>
    </>
  );
}
