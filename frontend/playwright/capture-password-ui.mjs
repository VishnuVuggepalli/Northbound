// One-off: capture the new password-management UI (user-menu modal + Settings Users).
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.NB_BASE ?? 'https://192.168.111.181';
const out = '/tmp/nb-ui';
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
  ignoreHTTPSErrors: true, // private CA; headless profile has no root installed
});
const page = await ctx.newPage();

await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
await page.fill('input[name="username"]', process.env.NB_USER ?? 'admin');
await page.fill('input[name="password"]', process.env.NB_PASS ?? 'northbound');
await page.click('button[type="submit"]');
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 15000 });
await page.waitForTimeout(1500);

// 1. User menu open (shows the Change password item).
await page.locator('header button', { hasText: /^[A-Z]{1,2}$/ }).last().click().catch(async () => {
  // fallback: the avatar button is the last button in the top bar
  await page.locator('header button').last().click();
});
await page.waitForTimeout(600);
await page.screenshot({ path: `${out}/1-user-menu.png` });

// 2. Change-password modal.
await page.getByText('Change password', { exact: true }).click();
await page.waitForTimeout(600);
await page.screenshot({ path: `${out}/2-change-password-modal.png` });
await page.keyboard.press('Escape');

// 3. Settings → Users section.
await page.goto(`${BASE}/settings`, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(1500);
await page.screenshot({ path: `${out}/3-settings-users.png`, fullPage: true });

// 4. Reset flow open on a row.
const resetBtn = page.getByText('Reset password…').first();
if (await resetBtn.count()) {
  await resetBtn.click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${out}/4-reset-inline.png`, fullPage: true });
}

await browser.close();
console.log('captured to', out);
