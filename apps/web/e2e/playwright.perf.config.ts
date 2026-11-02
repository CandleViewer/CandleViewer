import { defineConfig } from "@playwright/test";

// E22-S01 (#714) BQ-215: the tape's frame-rate proof, local and on demand, never a required check.
// It builds the app with the tape flag on (`VITE_FLAG_ORDERFLOW_TAPE=1`, the Playwright-only
// default, BQ-217) into a cache folder and serves it, then runs `perf/*.perf.ts` in Chromium.
//   pnpm --filter @candleviewer/web exec playwright test -c e2e/playwright.perf.config.ts
const PORT = process.env["TAPE_PERF_PORT"] ?? "4183";
const OUT = "node_modules/.cache/tape-perf";
export default defineConfig({
  testDir: "./perf",
  testMatch: /.*\.perf\.ts$/,
  timeout: 180_000,
  workers: 1,
  retries: 0,
  use: { baseURL: `http://127.0.0.1:${PORT}` },
  webServer: {
    command: `npx vite build --outDir ${OUT} --emptyOutDir && npx vite preview --outDir ${OUT} --port ${PORT} --host 127.0.0.1`,
    env: { VITE_FLAG_ORDERFLOW_TAPE: "1" },
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    cwd: "..",
    timeout: 300_000,
  },
});
