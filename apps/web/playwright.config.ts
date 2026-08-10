import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run start -- -p 3100",
    url: "http://127.0.0.1:3100",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    env: {
      // TEST EXECUTION ONLY (AUTH-001B1) -- see lib/server/auth-mode.ts.
      // This is what lets `next start` (NODE_ENV=production) boot and
      // serve deterministically without a configured Auth0 tenant. Every
      // existing FE-002B assertion below still intercepts `/api/**` at
      // the browser level (page.route), so these values never actually
      // reach a real backend -- they only need to be *present* so the
      // server's own auth-mode resolution and proxy/middleware layer
      // don't fail closed on missing real-auth configuration.
      CMP_TEST_AUTH_BYPASS: "playwright-e2e-only",
      CMP_TEST_TENANT_ID: "33333333-3333-3333-3333-333333333333",
      CMP_TEST_USER_ID: "44444444-4444-4444-4444-444444444444",
      CMP_API_BASE_URL: "http://127.0.0.1:9",
    },
  },
});
