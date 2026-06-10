/**
 * Time and unit formatters used across the UI.
 */

/** "1 device", "32 ports" — count + singular/plural noun. */
export function plural(count: number, noun: string, pluralForm?: string): string {
  const word = count === 1 ? noun : (pluralForm ?? `${noun}s`);
  return `${count} ${word}`;
}

export function timeAgo(epochMs: number, now: number = Date.now()): string {
  const diff = now - epochMs;
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return `${days} d ago`;
}

export function timeAgoMin(min: number): string {
  if (min < 1) return 'just now';
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

/**
 * Render a millisecond age as a short human string ("12s ago", "3m ago",
 * "2h ago"). Used by live freshness indicators where the user wants the
 * shortest possible reading.
 */
export function fmtAge(ms: number): string {
  if (ms < 1500) return 'just now';
  if (ms < 60_000) return `${Math.round(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m ago`;
  return `${Math.round(ms / 3_600_000)}h ago`;
}

export function formatSpeed(mbps: number | null): string {
  if (mbps == null) return '—';
  if (mbps >= 1000) return `${mbps / 1000} Gbps`;
  return `${mbps} Mbps`;
}

/** Dotted-quad IPv4 validator — four numeric octets, each 0–255. */
export function isPlausibleIp(s: string): boolean {
  if (!s) return false;
  const octets = s.split('.');
  if (octets.length !== 4) return false;
  return octets.every((o) => /^\d{1,3}$/.test(o) && Number(o) <= 255);
}

/** Initials for avatar from a full name. */
export function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((s) => s[0] ?? '')
    .join('')
    .slice(0, 2)
    .toUpperCase();
}
