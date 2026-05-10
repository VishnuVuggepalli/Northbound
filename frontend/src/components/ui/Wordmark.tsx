import { cn } from '@/lib/cn';

interface WordmarkProps {
  size?: number;
  glyph?: boolean;
  className?: string;
}

/**
 * Northbound wordmark — compass-needle motif. Stroke uses currentColor so it
 * inherits whatever the surrounding text color is.
 */
export function Wordmark({ size = 18, glyph = true, className }: WordmarkProps) {
  return (
    <span
      className={cn('inline-flex items-center gap-2 font-semibold tracking-tight', className)}
      style={{ fontSize: size }}
    >
      {glyph && (
        <svg width={size * 1.05} height={size * 1.05} viewBox="0 0 24 24" aria-hidden>
          <circle
            cx="12"
            cy="12"
            r="10.2"
            fill="none"
            stroke="currentColor"
            strokeOpacity={0.6}
            strokeWidth={1.2}
          />
          <path d="M12 3.5 L14.6 12.6 L12 11 L9.4 12.6 Z" fill="currentColor" />
          <path
            d="M12 20.5 L9.4 11.4 L12 13 L14.6 11.4 Z"
            fill="currentColor"
            fillOpacity={0.35}
          />
        </svg>
      )}
      <span>Northbound</span>
    </span>
  );
}
