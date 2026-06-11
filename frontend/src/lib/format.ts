/**
 * Time and unit formatters used across the UI.
 */
import ipaddr from 'ipaddr.js';

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

/**
 * Strict dotted-quad IPv4 validator, RFC-aligned with the Python backend.
 *
 * Backed by `ipaddr.js` (`IPv4.isValid`) rather than a hand-rolled regex.
 * ipaddr.js by itself accepts leading-zero octets (`01.02.03.04`), but the
 * backend's `ipaddress.ip_address` rejects them — so we additionally reject any
 * octet with a leading zero (unless it is exactly `"0"`) to match. Used for
 * router-id, BMC, and mgmt IP fields (addresses, not CIDRs).
 */
export function isPlausibleIp(s: string): boolean {
  if (!s || !ipaddr.IPv4.isValid(s)) return false;
  return s.split('.').every((o) => o === '0' || !o.startsWith('0'));
}

/**
 * IP-with-prefix validator for SVI / loopback addresses (e.g. `10.10.250.2/16`).
 * Backed by `ipaddr.js` `parseCIDR`, which covers both v4 and v6 with a prefix
 * and mirrors the backend's `ipaddress.ip_interface` check. A bare address with
 * no prefix is rejected.
 */
export function isPlausibleCidr(s: string): boolean {
  try {
    ipaddr.parseCIDR(s.trim());
    return true;
  } catch {
    return false;
  }
}

// One RFC 1123 label: 1..63 chars, alphanumeric + internal hyphen, no
// leading/trailing hyphen. Mirrors the backend `_HOSTNAME_LABEL_RE`.
const HOSTNAME_LABEL_RE = /^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$/;

/**
 * RFC 1123 host name: <=253 total, dot-separated labels each 1..63 chars,
 * alphanumeric + hyphen, no leading/trailing hyphen. Case-insensitive.
 *
 * Mirrors the backend `DeviceCreateIn.name` validator so the wizard rejects a
 * bad device name inline before the request is sent.
 */
export function isPlausibleHostname(s: string): boolean {
  if (!s || s.length > 253) return false;
  return s.split('.').every((label) => HOSTNAME_LABEL_RE.test(label));
}

/** OSPF area-id: a plain non-negative integer OR a dotted quad (0.0.0.0). */
export function isPlausibleArea(s: string): boolean {
  const v = s.trim();
  return /^\d+$/.test(v) || isPlausibleIp(v);
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
