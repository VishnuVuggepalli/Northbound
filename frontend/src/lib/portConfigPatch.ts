/**
 * Pure helpers for the admin Port Config editor: parse the tagged-VLAN text
 * field and compute the minimal PATCH body from the form state vs the live port.
 *
 * Kept out of the component so the diff logic is unit-testable — it guards a
 * data-loss bug (changing only the native VLAN of a trunk must not strip its
 * tagged VLANs).
 */

import type { PortConfigPatch } from '@/api/realClient';
import type { Port } from '@/types';

export type PortMode = 'access' | 'trunk';

/** Parse a "100, 200, 300" string into a sorted, de-duped, valid VLAN list. */
export function parseTagged(text: string): number[] {
  const ids = text
    .split(',')
    .map((s) => parseInt(s.trim(), 10))
    .filter((n) => Number.isInteger(n) && n >= 1 && n <= 4094);
  return [...new Set(ids)].sort((a, b) => a - b);
}

export function sameSet(a: readonly number[], b: readonly number[]): boolean {
  if (a.length !== b.length) return false;
  const sb = new Set(b);
  return a.every((x) => sb.has(x));
}

export interface PortConfigForm {
  mode: PortMode;
  native: number;
  tagged: number[];
  mtu: number;
  enabled: boolean;
}

/** Effective current mode of a port: trunk if it has tagged VLANs, else access. */
export function currentMode(port: Port): PortMode {
  return port.tagged_vlans.length > 0 ? 'trunk' : 'access';
}

/**
 * Minimal PATCH body: only fields that changed vs the live port.
 *
 * Critical invariant: any VLAN-touching change carries `port_mode` explicitly.
 * The backend infers access from "untagged set, tagged absent", so a native-only
 * edit on a trunk would otherwise be rewritten to access and lose its tagged
 * VLANs. With port_mode='trunk' and tagged omitted, the device merge keeps the
 * existing members.
 */
export function buildPortConfigPatch(port: Port, form: PortConfigForm): PortConfigPatch {
  const patch: PortConfigPatch = {};
  const modeChanged = form.mode !== currentMode(port);
  if (modeChanged) patch.port_mode = form.mode;
  if (modeChanged || form.native !== port.untagged_vlan) patch.untagged_vlan = form.native;
  if (form.mode === 'trunk' && (modeChanged || !sameSet(form.tagged, port.tagged_vlans))) {
    patch.tagged_vlans = form.tagged;
  }
  if ('untagged_vlan' in patch || 'tagged_vlans' in patch) {
    patch.port_mode = form.mode;
  }
  if (form.mtu !== port.mtu) patch.mtu = form.mtu;
  if (form.enabled !== port.admin_up) patch.enabled = form.enabled;
  return patch;
}
