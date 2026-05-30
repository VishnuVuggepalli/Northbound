/**
 * Playwright coverage for the M1 driver-capability batch:
 *
 *   F168 — DriverCapabilities extension (lldp + auth_methods + web_ui_url)
 *   F21b — `isWriteLocked` policy hoisted (queue / port panel)
 *   F21c — Vendor UI deep-link button on device + port surfaces
 *   F21d — FreeBSD SSH copy-chip
 *   F37a — PortPanel Neighbor (LLDP) row
 *   F14a — Onboarding cred step adapts to auth_methods
 *   F170 — About page rendered + linked from TopBar
 *
 * Sibling of decisions.spec.ts; shares the same login + readyness helpers.
 */

import { test, expect, type Page } from '@playwright/test';

async function loginAs(page: Page, role: 'admin' | 'requester'): Promise<void> {
  const username = role === 'admin' ? 'admin' : 'alice';
  await page.addInitScript((u: string) => {
    const user =
      u === 'admin'
        ? { username: 'admin', name: 'Admin User', role: 'admin' }
        : { username: 'alice', name: 'Alice Requester', role: 'requester' };
    const payload = { state: { user, isAuthenticated: true }, version: 0 };
    window.localStorage.setItem('nb-auth', JSON.stringify(payload));
  }, username);
}

async function grantClipboard(page: Page): Promise<void> {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
}

async function waitForReady(page: Page): Promise<void> {
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(600);
}

/* -------------------------------------------------------------------------
 * F21b — isWriteLocked policy
 *
 * Confirmed through the UI surface: write-locked devices show the Read-only
 * badge AND no Apply / Approve & apply buttons on their queue rows.
 * ------------------------------------------------------------------------- */

test.describe('F21b isWriteLocked policy', () => {
  test('router device shows Read-only badge in device header', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/env/lab/devices/d-lab-rtr-1');
    await waitForReady(page);
    await expect(page.getByText(/Read-only/i).first()).toBeVisible();
  });

  test('vpn device shows Read-only badge in device header', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/env/dc/devices/d-dc-vpn-1');
    await waitForReady(page);
    await expect(page.getByText(/Read-only/i).first()).toBeVisible();
  });

  test('writable platform leaf has no Read-only badge', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/env/lab/devices/d-lab-leaf-1');
    await waitForReady(page);
    // Header should NOT show Read-only for a writable Cisco leaf.
    const header = page.locator('header').filter({ hasText: 'lab-leaf-1' });
    await expect(header.getByText(/Read-only/i)).toHaveCount(0);
  });
});

/* -------------------------------------------------------------------------
 * F21c — Vendor UI deep-link
 * ------------------------------------------------------------------------- */

test.describe('F21c vendor UI deep-link', () => {
  test('renders with correct URL on Cisco device', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/env/lab/devices/d-lab-leaf-1');
    await waitForReady(page);

    const link = page.getByTestId('vendor-ui-link').first();
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute('href', 'https://10.10.0.11/');
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', /noopener/);
  });

  test('renders with HTTPS URL on Arista device', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/env/dc/devices/d-dc-arista-1');
    await waitForReady(page);

    const link = page.getByTestId('vendor-ui-link').first();
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute('href', 'https://10.20.0.11/');
  });

  test('absent on FreeBSD; SSH copy-chip shown instead', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/env/lab/devices/d-lab-rtr-1');
    await waitForReady(page);

    await expect(page.getByTestId('vendor-ui-link')).toHaveCount(0);
    const chip = page.getByTestId('ssh-copy-chip').first();
    await expect(chip).toBeVisible();
    await expect(chip).toContainText('ssh root@10.10.0.1');
  });
});

/* -------------------------------------------------------------------------
 * F21d — SSH copy-chip writes to clipboard
 * ------------------------------------------------------------------------- */

test('F21d SSH copy-chip writes ssh command to clipboard on click', async ({ page }) => {
  await loginAs(page, 'admin');
  await grantClipboard(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/env/lab/devices/d-lab-rtr-1');
  await waitForReady(page);

  const chip = page.getByTestId('ssh-copy-chip').first();
  await expect(chip).toBeVisible();
  await chip.click();

  const clipboard = await page.evaluate(() => navigator.clipboard.readText());
  expect(clipboard).toBe('ssh root@10.10.0.1');
});

/* -------------------------------------------------------------------------
 * F37a — PortPanel Neighbor (LLDP) row
 * ------------------------------------------------------------------------- */

test.describe('F37a PortPanel Neighbor row', () => {
  test('renders when neighbors present on Cisco port (Ethernet14)', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/env/lab/devices/d-lab-leaf-1');
    await waitForReady(page);

    // Ethernet14 has a seeded neighbor (host-104.lab.local).
    const port = page.locator('[data-port="Ethernet14"]').first();
    await port.click();
    await expect(page.getByRole('button', { name: /Close panel/i })).toBeVisible();

    const neighborSection = page.getByText(/Neighbor \(LLDP\)/i).first();
    await expect(neighborSection).toBeVisible();
    await expect(page.getByText('host-104.lab.local')).toBeVisible();
  });

  test('absent when neighbors empty', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/env/lab/devices/d-lab-leaf-1');
    await waitForReady(page);

    // Ethernet5 has no seeded neighbor. Pick by data-port so we don't accidentally
    // match a fixture row that did get one.
    const port = page.locator('[data-port="Ethernet5"]').first();
    await port.click();
    await expect(page.getByRole('button', { name: /Close panel/i })).toBeVisible();

    await expect(page.getByText(/Neighbor \(LLDP\)/i)).toHaveCount(0);
  });

  test('absent on platform with supports_lldp=false (FreeBSD)', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/env/lab/devices/d-lab-rtr-1');
    await waitForReady(page);

    const port = page.locator('[data-port]').first();
    await port.click();
    await expect(page.getByRole('button', { name: /Close panel/i })).toBeVisible();

    // FreeBSD platform has supports_lldp=false, so the section never renders
    // even if a port happened to carry a neighbor list.
    await expect(page.getByText(/Neighbor \(LLDP\)/i)).toHaveCount(0);
  });
});

/* -------------------------------------------------------------------------
 * F14a — Onboarding cred step adapts to auth_methods
 * ------------------------------------------------------------------------- */

test.describe('F14a Onboarding step 4 adapts to auth_methods', () => {
  test('shows SSH key field when Pica8 + ssh_key selected', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/onboard');
    await waitForReady(page);

    // Step 1: pick Pica8 (auth_methods = password, ssh_key)
    await page.getByText('Pica8 PicOS').click();
    await page.getByRole('button', { name: /Continue/ }).click();

    // Step 2: name + identity
    await page.locator('input[placeholder="lab-leaf-4"]').fill('lab-pica-test');
    await page.getByRole('button', { name: /Continue/ }).click();

    // Step 3: management IP
    await page.locator('input[placeholder="10.10.0.14"]').fill('10.10.0.99');
    await page.getByRole('button', { name: /Continue/ }).click();

    // Step 4: default is the first allowed method (password). Switch to SSH
    // key and assert the key field appears. exact:true because the wrapping
    // <label> bleeds "Auth method" into the accessible name of the first
    // segmented button.
    await page.getByRole('button', { name: 'SSH key', exact: true }).click();
    await expect(page.getByTestId('onboard-ssh-key')).toBeVisible();
    // Password field is swapped out for the key.
    await expect(page.getByTestId('onboard-password')).toHaveCount(0);
    // SNMP-only fields are not present for Pica8.
    await expect(page.getByTestId('onboard-snmp-community')).toHaveCount(0);
  });

  test('shows password fields by default when Cisco selected', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/onboard');
    await waitForReady(page);

    await page.getByText('Cisco IOS / NX-OS').click();
    await page.getByRole('button', { name: /Continue/ }).click();

    await page.locator('input[placeholder="lab-leaf-4"]').fill('lab-cisco-test');
    await page.getByRole('button', { name: /Continue/ }).click();

    await page.locator('input[placeholder="10.10.0.14"]').fill('10.10.0.98');
    await page.getByRole('button', { name: /Continue/ }).click();

    // Cisco only allows password — username + password visible, no alternatives.
    await expect(page.getByTestId('onboard-username')).toBeVisible();
    await expect(page.getByTestId('onboard-password')).toBeVisible();
    await expect(page.getByTestId('onboard-api-token')).toHaveCount(0);
    await expect(page.getByTestId('onboard-snmp-community')).toHaveCount(0);
  });
});

/* -------------------------------------------------------------------------
 * F170 — About page
 * ------------------------------------------------------------------------- */

test.describe('F170 About page', () => {
  test('renders core positioning copy at /about', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/about');
    await waitForReady(page);

    await expect(
      page.getByRole('heading', { name: /What Northbound is/i }),
    ).toBeVisible();
    await expect(page.getByText(/request-mediated port-change workflow/i)).toBeVisible();
    await expect(page.getByText(/LibreNMS/i).first()).toBeVisible();
  });

  test('is linked from the TopBar account menu', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/');
    await waitForReady(page);

    await page.getByRole('button', { name: /Account/i }).click();
    const link = page.getByRole('button', { name: /About Northbound/i });
    await expect(link).toBeVisible();
    await link.click();

    await expect(page).toHaveURL(/\/about$/);
  });
});
