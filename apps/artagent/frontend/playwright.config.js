// @ts-check
import { defineConfig } from '@playwright/test';

const port = Number(process.env.PLAYWRIGHT_PORT || 5173);
const baseURL = `http://localhost:${port}`;
const browserName = process.env.PLAYWRIGHT_BROWSER || 'chromium';
if (browserName !== 'chromium' && browserName !== 'webkit' && browserName !== 'firefox') {
  throw new Error('PLAYWRIGHT_BROWSER must be chromium, webkit, or firefox.');
}

/**
 * Playwright E2E test configuration for scenario switching.
 *
 * Tests use route-level API mocking (page.route) so they don't require
 * a running backend.  Only the Vite frontend dev server is needed.
 *
 * Usage:
 *   cd apps/artagent/frontend
 *   npx playwright test                       # run all
 *   npx playwright test --headed              # watch in browser
 *   npx playwright test -g "scenario"         # filter by name
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,           // scenarios share session state
  retries: 0,                     // no retries — tests must be deterministic
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: browserName,
      use: { browserName },
    },
  ],
  webServer: {
    command: `npm run dev -- --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: true,    // use existing Vite server if running
    timeout: 30_000,
  },
});
