import { test, expect } from '@playwright/test';

// Runs on both Desktop Chrome and an emulated iPhone (see playwright.config.ts),
// which guards the mobile rendering path that the iOS auth fix depended on.
test('login screen renders', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByPlaceholder(/analyst@/i)).toBeVisible();
  await expect(page.getByText(/SIGN_IN/)).toBeVisible();
  await expect(page.getByText(/Identify Threats/i)).toBeVisible();
});

test('can switch to the sign-up tab', async ({ page }) => {
  await page.goto('/');
  await page.getByText(/SIGN_UP \/ REGISTER/i).click();
  await expect(page.getByText(/ANALYST IDENTITY/i)).toBeVisible();
});
