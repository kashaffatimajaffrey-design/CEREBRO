import { defineConfig, devices } from '@playwright/test';

// End-to-end smoke tests. Builds the app and serves the production bundle, then
// drives it in a real browser. No backend is required for the login-screen smoke
// check (the SPA renders the auth screen before any authenticated call).
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
  },
  expect: {
    // Visual regression defaults (see e2e/visual.spec.ts).
    toHaveScreenshot: {
      // Hold CSS and Web Animations API transitions at their end state, so a
      // Framer Motion entrance cannot be caught mid-flight.
      animations: 'disabled',
      caret: 'hide',
      // Subpixel antialiasing still varies slightly between runs on the same
      // machine. This is tight enough to catch a moved element or a colour
      // change and loose enough not to fail on text rasterisation noise.
      maxDiffPixelRatio: 0.01,
      threshold: 0.2,
    },
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile-safari', use: { ...devices['iPhone 13'] } },
  ],
  webServer: {
    command: 'npm run build:client && npm run preview -- --port 4173 --strictPort',
    url: 'http://localhost:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
