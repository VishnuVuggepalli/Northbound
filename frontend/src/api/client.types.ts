/**
 * Shared client interface types.
 *
 * Both the mock (`client.ts`) and real (`realClient.ts`) clients implement the
 * same function surface; these input/result shapes are the contract between
 * them. Keeping them here (instead of in either client) means the selector in
 * `index.ts` and the unit tests can reason about one canonical interface.
 */

import type { RequestedChanges, User } from '@/types';

export interface LoginResult {
  user: User;
  access_token: string;
}

export interface CreateRequestInput {
  device_id: string;
  port_name: string;
  requested_by: string;
  requested_changes: RequestedChanges;
  reason: string;
}

export interface TestConnectionResult {
  ok: boolean;
  latency_ms: number;
  message: string;
}

export interface DiscoverResult {
  port_count: number;
  sample_ports: string[];
  config_excerpt: string;
}

export interface ConfirmOnboardResult {
  device: import('@/types').Device;
  ports_seeded: number;
}
