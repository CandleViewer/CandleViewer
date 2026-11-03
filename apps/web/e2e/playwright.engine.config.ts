import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";
import { PINNED_CHROMIUM_FLAGS } from "./engine-harness/chromium-flags";

// E11-Q02 (#444) engine interaction E2E: specs/e11-chart against the harness's own build (:4175).
// Run: `pnpm --filter @candleviewer/web e2e:engine`. Zero retries (BQ-10, AC5): a flaky spec is
// tagged `@flaky`, never retried. No `toHaveScreenshot`: goldens are E11-T08.
const HERE = path.dirname(fileURLToPath(import.meta.url));
export const ENGINE_URL = process.env["CV_ENGINE_HARNESS_URL"] ?? "http://127.0.0.1:4175";
const FLAKY = /@flaky/u;
const QUARANTINE = process.env["CV_E2E_QUARANTINE"] === "1";

export default defineConfig({
  testDir: "./specs/e11-chart",
  testMatch: "**/*.spec.ts",
  timeout: 30_000, // a liveness bound: catches a hang, not a slowdown
  retries: 0,
  workers: 1,
  projects: QUARANTINE
    ? [{ name: "flaky-nightly", grep: FLAKY }]
    : [
        {
          name: "chromium",
          grepInvert: FLAKY,
          use: { launchOptions: { args: [...PINNED_CHROMIUM_FLAGS] } },
        },
      ],
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: path.resolve(HERE, "../playwright-report/engine") }],
  ],
  use: {
    baseURL: ENGINE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command:
      "npx vite build -c e2e/engine-harness/vite.config.ts && " +
      "npx vite preview -c e2e/engine-harness/vite.config.ts --port 4175 --strictPort --host 127.0.0.1",
    url: ENGINE_URL,
    cwd: path.resolve(HERE, ".."),
    reuseExistingServer: !process.env["CI"],
    timeout: 300_000,
  },
});
