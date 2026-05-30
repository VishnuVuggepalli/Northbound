/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Base URL for the real backend API. Empty string = same-origin (default).
   * e.g. `http://localhost:8090` when running the dev server against a
   * separately-hosted backend.
   */
  readonly VITE_API_BASE?: string;
  /**
   * `"false"` switches the app onto the real `fetch` client. Anything else
   * (including unset) keeps the in-memory mock client so dev + Playwright E2E
   * stay fully offline. Default: mocks ON.
   */
  readonly VITE_USE_MOCKS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
