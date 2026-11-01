import { defineConfig } from "@playwright/test";

// E10-Q04 shell cold-start harness (budget #10): on demand (`pnpm --filter @candleviewer/desktop
// perf`), recording only, never a required check. Its own config so the PR e2e lane never runs it.
// It needs `apps/web/dist` and `apps/desktop/dist` built; the stub backend serves the web build, so
// there is no webServer here. One worker, no retries: a retry would hide a cold-start outlier.
export default defineConfig({
  testDir: ".",
  testMatch: /\.perf\.ts$/u,
  timeout: 15 * 60_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
});
