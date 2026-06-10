/**
 * Non-component exports shared by the device-system forms — kept out of the
 * component files so each of those exports only components (react-refresh
 * fast-refresh requirement).
 */

import { pushToast } from '@/store/toast';

export interface VlanFormInitial {
  vid: string;
  name: string;
  desc: string;
}

export const EMPTY_VLAN_FORM: VlanFormInitial = { vid: '', name: '', desc: '' };

export interface L3FormInitial {
  kind: 'svi' | 'loopback';
  vid: string;
  name: string;
  ip: string;
  mtu: string;
  vrf: string;
}

export const EMPTY_L3_FORM: L3FormInitial = {
  kind: 'svi',
  vid: '',
  name: '',
  ip: '',
  mtu: '',
  vrf: '',
};

export interface OspfFormInitial {
  target: 'interface' | 'router-id';
  iface: string;
  area: string;
  routerId: string;
  cost: string;
}

export const EMPTY_OSPF_FORM: OspfFormInitial = {
  target: 'interface',
  iface: '',
  area: '0.0.0.0',
  routerId: '',
  cost: '',
};

/** Standard error toast for a change-request filing that failed. */
export function filingErrorToast(err: unknown): void {
  pushToast({
    kind: 'error',
    title: 'Could not file request',
    message: err instanceof Error ? err.message : 'Failed',
  });
}
