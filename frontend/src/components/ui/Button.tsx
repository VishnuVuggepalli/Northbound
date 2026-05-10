import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/cn';

const buttonStyles = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:pointer-events-none disabled:opacity-50 select-none',
  {
    variants: {
      kind: {
        primary:
          'bg-accent text-accent-fg hover:brightness-110 active:brightness-95 shadow-[0_1px_0_0_rgba(255,255,255,0.06)_inset]',
        ghost: 'bg-transparent text-fg hover:bg-bg-elev-2',
        outline:
          'border border-border-strong bg-transparent text-fg hover:bg-bg-elev-2',
        success:
          'bg-success/85 text-[oklch(0.12_0.05_145)] hover:bg-success',
        danger:
          'bg-danger/85 text-[oklch(0.99_0.01_25)] hover:bg-danger',
        link: 'text-accent hover:underline underline-offset-4 px-1',
      },
      size: {
        sm: 'h-7 px-2.5 text-xs',
        md: 'h-9 px-3.5 text-sm',
        lg: 'h-11 px-5 text-base',
        icon: 'h-9 w-9 p-0',
      },
    },
    defaultVariants: { kind: 'ghost', size: 'md' },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonStyles> {
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, kind, size, leftIcon, rightIcon, children, ...rest },
  ref,
) {
  return (
    <button ref={ref} className={cn(buttonStyles({ kind, size }), className)} {...rest}>
      {leftIcon}
      {children}
      {rightIcon}
    </button>
  );
});
