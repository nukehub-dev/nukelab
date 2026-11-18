import { defineConfig, devices } from '@playwright/test'
import { BASE_URL, EXTERNAL_SERVER } from './e2e/helpers/runtime'

// Two supported modes:
// - Local development (default): Playwright starts Vite and uses
//   http://localhost:5173.
// - Prestarted stack: set E2E_EXTERNAL_SERVER=1 (and optionally BASE_URL) to
//   target a single-origin deployment such as the frontend behind Traefik on
//   http://localhost:8080. No Vite web server is started in this mode.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // The real stack shares container capacity; keep one browser worker.
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: EXTERNAL_SERVER
    ? undefined
    : {
        command: 'npm run dev',
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 120000,
      },
})
