import {
  forwardRef,
  type AnchorHTMLAttributes,
  type ButtonHTMLAttributes,
  type ReactNode,
} from 'react';
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

interface CommonButtonProps extends VariantProps<typeof buttonStyles> {
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

type ButtonAsButton = CommonButtonProps &
  ButtonHTMLAttributes<HTMLButtonElement> & {
    href?: undefined;
  };

type ButtonAsAnchor = CommonButtonProps &
  Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'type'> & {
    /**
     * When set, the Button renders as `<a>` so middle-click / cmd-click / new
     * tab work — critical for NOC users opening vendor UIs. `target="_blank"`
     * automatically gets `rel="noopener noreferrer"`.
     */
    href: string;
  };

export type ButtonProps = ButtonAsButton | ButtonAsAnchor;

function isAnchorProps(props: ButtonProps): props is ButtonAsAnchor {
  return typeof (props as ButtonAsAnchor).href === 'string';
}

export const Button = forwardRef<HTMLButtonElement | HTMLAnchorElement, ButtonProps>(
  function Button(props, ref) {
    const { className, kind, size, leftIcon, rightIcon, children } = props;
    const classes = cn(buttonStyles({ kind, size }), className);

    if (isAnchorProps(props)) {
      const {
        className: _c,
        kind: _k,
        size: _s,
        leftIcon: _l,
        rightIcon: _r,
        children: _ch,
        target,
        rel,
        ...rest
      } = props;
      // Force-attach noopener for any _blank target. Don't silently overwrite
      // a caller-supplied rel.
      const safeRel =
        target === '_blank' ? (rel ? `${rel} noopener noreferrer` : 'noopener noreferrer') : rel;
      return (
        <a
          ref={ref as React.Ref<HTMLAnchorElement>}
          className={classes}
          target={target}
          rel={safeRel}
          {...rest}
        >
          {leftIcon}
          {children}
          {rightIcon}
        </a>
      );
    }

    const {
      className: _c,
      kind: _k,
      size: _s,
      leftIcon: _l,
      rightIcon: _r,
      children: _ch,
      href: _h,
      ...rest
    } = props;
    return (
      <button ref={ref as React.Ref<HTMLButtonElement>} className={classes} {...rest}>
        {leftIcon}
        {children}
        {rightIcon}
      </button>
    );
  },
);
