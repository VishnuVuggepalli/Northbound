/**
 * Active API client selector.
 *
 * `VITE_USE_MOCKS` controls which implementation the whole app talks to:
 *
 *   - unset / anything but `"false"`  → mock client (default). Dev server and
 *     Playwright E2E run fully offline against in-memory fixtures.
 *   - `"false"`                       → real `fetch` client against the
 *     FastAPI backend (`VITE_API_BASE`, default same-origin).
 *
 * Both modules implement the identical function surface (`client.types.ts` is
 * the shared contract), so `queries.ts` and components import from here and
 * never branch on which client is live.
 */

import * as mockClient from './client';
import * as realClient from './realClient';

/** True when the mock client is active. Default: true (offline-first). */
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS !== 'false';

type ApiClient = typeof mockClient & {
  confirmRequest: typeof realClient.confirmRequest;
  logout: typeof realClient.logout;
};

export const apiClient: ApiClient = (USE_MOCKS ? mockClient : realClient) as ApiClient;

export type {
  ConfirmOnboardResult,
  CreateRequestInput,
  DiscoverResult,
  LoginResult,
  TestConnectionResult,
} from './client.types';
export { ApiError, isApiError } from './errors';
export { VLANS } from '@/mocks/fixtures';
