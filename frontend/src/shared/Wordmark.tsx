import { cn } from '@/lib/cn';

interface WordmarkProps {
  size?: number;
  glyph?: boolean;
  /**
   * Play the compass-needle "lock to north" entrance animation on the glyph.
   * Used on the marquee surfaces (login, env-picker). Respects
   * prefers-reduced-motion via the global stylesheet.
   */
  animate?: boolean;
  className?: string;
}

/**
 * Northbound wordmark — a compass-rose motif. The needle points true north;
 * faint cardinal ticks frame it like an instrument bezel. Stroke uses
 * currentColor so the mark inherits the surrounding text color, and the
 * north-half of the needle picks up the accent for the brand signature.
 */
export function Wordmark({ size = 18, glyph = true, animate = false, className }: WordmarkProps) {
  const dim = size * 1.18;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 font-semibold tracking-tightest',
        className,
      )}
      style={{ fontSize: size }}
    >
      {glyph && (
        <svg
          width={dim}
          height={dim}
          viewBox="0 0 24 24"
          aria-hidden
          className={animate ? 'nb-compass-lock' : undefined}
        >
          {/* Bezel */}
          <circle
            cx="12"
            cy="12"
            r="10.4"
            fill="none"
            stroke="currentColor"
            strokeOpacity={0.55}
            strokeWidth={1.1}
          />
          {/* Cardinal ticks */}
          <g stroke="currentColor" strokeOpacity={0.35} strokeWidth={1}>
            <line x1="12" y1="2.4" x2="12" y2="4.2" />
            <line x1="12" y1="19.8" x2="12" y2="21.6" />
            <line x1="2.4" y1="12" x2="4.2" y2="12" />
            <line x1="19.8" y1="12" x2="21.6" y2="12" />
          </g>
          {/* Needle — north half takes the accent, south half dims. */}
          <path d="M12 4 L14.7 12.4 L12 10.9 L9.3 12.4 Z" fill="var(--nb-accent)" />
          <path
            d="M12 20 L9.3 11.6 L12 13.1 L14.7 11.6 Z"
            fill="currentColor"
            fillOpacity={0.3}
          />
          {/* Hub */}
          <circle cx="12" cy="12" r="1.05" fill="currentColor" />
        </svg>
      )}
      <span>Northbound</span>
    </span>
  );
}
