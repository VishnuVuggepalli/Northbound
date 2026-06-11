/**
 * Active API client.
 *
 * The app talks ONLY to the real FastAPI backend — no mock client. Requests go
 * to `VITE_API_BASE` (default same-origin; the Vite dev server proxies `/api/*`
 * to the backend). `realClient` is the single implementation; `client.types.ts`
 * is the shared contract consumed by `queries.ts` and components.
 */

import * as realClient from './realClient';

export const apiClient = realClient;

export { isApiError } from './errors';
