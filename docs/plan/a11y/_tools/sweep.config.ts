import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

// E47-T01 (#1323) sweep driver config (docs/plan/a11y/_tools/e47-sweep.qa.ts). Run from apps/web so
// apps/web's Playwright is the runner; this directory's tsconfig.json maps @playwright/test and
// @axe-core/playwright onto apps/web's copies (no new dependency):
//
//   cd apps/web && A11Y_MODE=automated A11Y_SHA=$(git rev-parse HEAD) \
//     npx playwright test -c ../../docs/plan/a11y/_tools/sweep.config.ts
//
// It serves the existing apps/web build (`vite preview`, loopback only); build first. Results go to
// A11Y_OUT (default under the OS temp directory), never into the repository.
const PORT = process.env["A11Y_PORT"] ?? "4174";
export default defineConfig({
  testDir: ".",
  testMatch: /e47-sweep\.qa\.ts$/,
  outputDir: join(process.env["A11Y_OUT"] ?? join(tmpdir(), "e47-t01-sweep"), "pw-test-results"),
  timeout: 3_600_000,
  workers: 1,
  retries: 0,
  reporter: "line",
  use: { baseURL: `http://127.0.0.1:${PORT}`, screenshot: "off", video: "off", trace: "off" },
  webServer: {
    command: `npx vite preview --port ${PORT} --host 127.0.0.1 --strictPort`,
    cwd: "../../../../apps/web",
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
