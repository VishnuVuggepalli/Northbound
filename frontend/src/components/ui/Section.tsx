import { useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/cn';

interface SectionProps {
  title: ReactNode;
  defaultOpen?: boolean;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Section({
  title,
  defaultOpen = true,
  right,
  children,
  className,
}: SectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className={cn('border-b border-border last:border-b-0', className)}>
      <header className="flex items-center gap-2 px-1 py-2">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex flex-1 items-center gap-2 text-left text-xs font-semibold uppercase tracking-wider text-fg-muted hover:text-fg"
        >
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <span>{title}</span>
        </button>
        {right && <div onClick={(e) => e.stopPropagation()}>{right}</div>}
      </header>
      {open && <div className="pb-3 pt-1">{children}</div>}
    </section>
  );
}
