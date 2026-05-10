import { CheckCircle2, AlertCircle, Info, AlertTriangle } from 'lucide-react';
import { useToastStore, type ToastKind } from '@/store/toast';
import { cn } from '@/lib/cn';

const ICON: Record<ToastKind, typeof Info> = {
  info: Info,
  success: CheckCircle2,
  warn: AlertTriangle,
  error: AlertCircle,
};

const ACCENT: Record<ToastKind, string> = {
  info: 'text-accent',
  success: 'text-success',
  warn: 'text-warn',
  error: 'text-danger',
};

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  return (
    <div
      aria-live="polite"
      aria-atomic="true"
      className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[380px] max-w-[calc(100vw-2rem)] flex-col gap-2"
    >
      {toasts.map((t) => {
        const Icon = ICON[t.kind];
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => dismiss(t.id)}
            className="pointer-events-auto nb-card animate-fade-in flex w-full items-start gap-3 border-border-strong px-3.5 py-3 text-left shadow-xl"
          >
            <Icon size={16} className={cn('mt-0.5 shrink-0', ACCENT[t.kind])} />
            <div className="min-w-0 flex-1">
              {t.title && (
                <div className="truncate text-sm font-semibold text-fg">{t.title}</div>
              )}
              {t.message && (
                <div className="mt-0.5 text-xs text-fg-muted">{t.message}</div>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}
