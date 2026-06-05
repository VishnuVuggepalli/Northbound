import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          'flex h-9 w-full rounded-md border border-border bg-bg-elev-1 px-3 text-sm text-fg placeholder:text-fg-subtle',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:border-accent/60',
          'disabled:cursor-not-allowed disabled:opacity-50',
          className,
        )}
        {...rest}
      />
    );
  },
);

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...rest }, ref) {
  return (
    <textarea
      ref={ref}
      className={cn(
        'flex min-h-[60px] w-full rounded-md border border-border bg-bg-elev-1 px-3 py-2 text-sm text-fg placeholder:text-fg-subtle',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:border-accent/60',
        'disabled:cursor-not-allowed disabled:opacity-50 resize-y',
        className,
      )}
      {...rest}
    />
  );
});
