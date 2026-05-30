/**
 * Playwright coverage for the four product decisions shipped in this PR.
 *
 * D1 — Apply confirmation modal in admin queue
 * D2 — "Edit directly" stub removed from PortPanel
 * D3 — Stale-data warning band on PortPanel
 * D4 — Bundle size accepted (no test, doc-only — see UX_AUDIT.md)
 *
 * Lives next to heuristic.spec.ts. The dev server, axe rig, and login helper
 * are all reused from that spec so this file stays narrow.
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

async function waitForReady(page: Page): Promise<void> {
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(800);
}

/* -------------------------------------------------------------------------
 * D1 — Apply confirmation modal
 * ------------------------------------------------------------------------- */

test.describe('D1 apply confirmation modal', () => {
  test('opens before apply, Cancel keeps request pending, Apply now confirms', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/queue');
    await waitForReady(page);

    // r-001 (alice → d-lab-leaf-1 / Ethernet14, status: pending) is seeded
    // in fixtures.ts. Expand the row so action buttons render.
    const row = page.getByRole('button').filter({ hasText: '#r-001' }).first();
    await expect(row).toBeVisible();
    await row.click();

    // Approve & apply must NOT fire the mutation — it must open the modal.
    const approveApply = page.getByTestId('approve-apply');
    await expect(approveApply).toBeVisible();
    await approveApply.click();

    // Modal opens with the rendered config delta inside.
    const dialog = page.getByRole('dialog').filter({ hasText: /Apply change to/i });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText(/Rendered config delta/i)).toBeVisible();

    // Cancel closes the modal without applying. Status should still read
    // "pending" on the row.
    await dialog.getByRole('button', { name: /^Cancel$/ }).click();
    await expect(dialog).toBeHidden();
    await expect(row).toContainText(/pending/i);

    // Re-open and confirm. The row should disappear from the queue (queue
    // only shows pending+approved, applied requests drop off).
    await approveApply.click();
    const confirmDialog = page.getByRole('dialog').filter({ hasText: /Apply change to/i });
    await expect(confirmDialog).toBeVisible();
    await confirmDialog.getByTestId('apply-confirm').click();
    await expect(confirmDialog).toBeHidden();
    // After mock apply (~600ms) the row drops from the queue.
    await expect(page.getByRole('button').filter({ hasText: '#r-001' })).toHaveCount(0, {
      timeout: 5_000,
    });
  });

  test('Esc closes the apply confirmation modal without firing', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/queue');
    await waitForReady(page);

    const row = page.getByRole('button').filter({ hasText: '#r-002' }).first();
    await expect(row).toBeVisible();
    await row.click();

    await page.getByTestId('approve-apply').click();
    const dialog = page.getByRole('dialog').filter({ hasText: /Apply change to/i });
    await expect(dialog).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(row).toContainText(/pending/i);
  });
});

/* -------------------------------------------------------------------------
 * D2 — "Edit directly" button removed from PortPanel
 * ------------------------------------------------------------------------- */

test('D2 PortPanel does not render an "Edit directly" button', async ({ page }) => {
  await loginAs(page, 'admin');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/env/lab/devices/d-lab-leaf-1');
  await waitForReady(page);

  // Open the port panel so the admin footer renders.
  await page.locator('[data-port]').first().click();
  await expect(page.getByRole('button', { name: /Close panel/i })).toBeVisible();

  // The stub was removed entirely.
  await expect(page.getByRole('button', { name: /Edit directly/i })).toHaveCount(0);
});

/* -------------------------------------------------------------------------
 * D3 — Stale-data warning band on PortPanel
 *
 * We can't naturally wait 60s in a test, so we install a fake clock,
 * navigate (TanStack records dataUpdatedAt against the fake "now"),
 * then jump the clock forward 90s and let the 5s tick pick up the
 * transition.
 * ------------------------------------------------------------------------- */

test('D3 PortPanel shows stale warning band when data > 60s old', async ({ page }) => {
  await loginAs(page, 'admin');

  // Pin time at a known epoch, then advance after the fetch settles.
  const T0 = new Date('2026-05-10T12:00:00Z');
  await page.clock.install({ time: T0 });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/env/lab/devices/d-lab-leaf-1');
  await waitForReady(page);

  // Open the port panel.
  await page.locator('[data-port]').first().click();
  await expect(page.getByRole('button', { name: /Close panel/i })).toBeVisible();

  // Initially fresh — the muted/subtle status row is present, the stale band
  // is not.
  await expect(page.getByTestId('port-fresh-status')).toBeVisible();
  await expect(page.getByTestId('port-stale-band')).toHaveCount(0);

  // Jump 90 seconds forward — past the 60s threshold. The 5s tick inside the
  // panel will fire (clock.fastForward also advances setInterval), so the
  // amber band should appear.
  await page.clock.fastForward(90_000);

  await expect(page.getByTestId('port-stale-band')).toBeVisible();
  await expect(page.getByTestId('port-stale-band')).toContainText(/Data may be stale/i);
  await expect(page.getByTestId('port-fresh-status')).toHaveCount(0);

  // Refetch button inside the band resets the timer.
  await page.getByTestId('port-stale-band').getByRole('button', { name: /Refetch/i }).click();
  // After refetch + a tick, the band should disappear (TanStack updates
  // dataUpdatedAt to "now"; new age is < 30s).
  await page.clock.fastForward(1_000);
  await expect(page.getByTestId('port-stale-band')).toHaveCount(0, { timeout: 5_000 });
});
