import { defineConfig } from "@playwright/test";

// E17-Q04 (#569): the real-time lane, AC 2's and AC 3's budgets measured on the shipped bundle (`dist/`). Its specs
// end in `.nightly.ts`, which the stub lane's `playwright.config.ts` (`*.spec.ts`) never matches, so a wall-clock
// number never gates a PR. The measurement is the test's `measured` annotation, kept in the report.
const port = process.env["CV_E2E_NIGHTLY_PREVIEW_PORT"] ?? "4176";
const origin = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e17",
  testMatch: "**/*.nightly.ts",
  timeout: 30_000,
  retries: 0,
  forbidOnly: true,
  workers: 1,
  outputDir: "../test-results/e17-nightly",
  use: {
    baseURL: origin,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: `npx vite preview --port ${port} --strictPort --host 127.0.0.1`,
    url: origin,
    reuseExistingServer: false,
    cwd: "..",
    timeout: 120_000,
  },
});
