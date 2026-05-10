import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for Northbound UX audit.
 *
 * - Single chromium project at three viewports rendered via per-test setViewportSize.
 * - Dev server is expected on http://localhost:5173 (started externally so we can
 *   share it across runs).
 * - Screenshots are stored under playwright/screenshots/.
 */
export default defineConfig({
  testDir: './playwright',
  testMatch: /.*\.spec\.ts/,
  globalSetup: './playwright/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? 'list' : 'list',
  use: {
    baseURL: process.env.PW_BASE_URL ?? 'http://localhost:5173',
    headless: true,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
