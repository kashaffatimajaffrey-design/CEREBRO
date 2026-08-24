import { test, expect, type Page } from '@playwright/test';

/**
 * Visual regression.
 *
 * Screenshots are compared against committed PNG baselines, so a change that
 * type-checks, lints and passes every unit test but silently breaks the layout
 * still turns the pipeline red. That is the failure mode none of the other
 * checks can see.
 *
 * Two things about this app make naive screenshotting useless, and both are
 * handled below rather than papered over with a loose threshold:
 *
 *  - A full-viewport <canvas> particle field animates every frame, so no two
 *    screenshots of the same page are ever identical. It is hidden with an
 *    injected stylesheet rather than passed to Playwright's `mask` option:
 *    because the canvas covers the whole viewport, masking paints the entire
 *    page a flat colour and the assertion silently stops testing anything.
 *    `visibility: hidden` removes the moving pixels and keeps the layout.
 *  - Framer Motion entrance transitions mean the page keeps moving after load.
 *    `animations: 'disabled'` (set in playwright.config.ts) finishes them
 *    instantly and holds them at their end state.
 *
 * Baselines are platform-specific: font rasterisation and antialiasing differ
 * between Windows and the Linux runner. They are generated on the runner by
 * .github/workflows/update-snapshots.yml, so the suite only runs where those
 * baselines are meaningful. Set VISUAL=1 to force it anywhere.
 */

const baselinesAreValidHere =
  !!process.env.CI || process.platform === 'linux' || !!process.env.VISUAL;

test.describe('visual regression', () => {
  test.skip(
    !baselinesAreValidHere,
    'Baselines are rendered on Linux; comparing them against a Windows or macOS ' +
      'render reports font differences as regressions. Runs in CI.',
  );

  /** Settle the page: canvas stilled, fonts loaded, entrance animations done. */
  async function ready(page: Page) {
    await page.goto('/');
    await page.addStyleTag({ content: 'canvas { visibility: hidden !important; }' });
    await page.evaluate(() => document.fonts.ready);
    // The auth form is the last thing to mount; once its input is visible the
    // layout is final.
    await expect(page.getByPlaceholder(/analyst@/i)).toBeVisible();
  }

  test('sign-in screen', async ({ page }) => {
    await ready(page);
    await expect(page).toHaveScreenshot('sign-in.png', { fullPage: true });
  });

  test('sign-up screen', async ({ page }) => {
    await ready(page);
    await page.getByText(/SIGN_UP \/ REGISTER/i).click();
    await expect(page.getByText(/ANALYST IDENTITY/i)).toBeVisible();
    await expect(page).toHaveScreenshot('sign-up.png', { fullPage: true });
  });
});
