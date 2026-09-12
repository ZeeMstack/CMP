import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    // PILOT-BLOCKER-006: Vitest owns unit/component/page tests only.
    // e2e/*.spec.ts are Playwright tests (see playwright.config.ts) and
    // must never be collected here -- they import @playwright/test's own
    // `test`/`expect`, which fails outside a Playwright test runner.
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules", ".next", "e2e/**"],
  },
});
