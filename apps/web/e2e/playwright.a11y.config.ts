import { defineConfig } from "@playwright/test";
import { HARNESS_ORIGIN, HARNESS_PORT } from "./a11y/chart-harness/surfaces";

// E47-T02: accessibility collectors. They emit JSON/text under reports/a11y/
// for tools/a11y/gates.py to judge; a collector fails only when it cannot
// collect (infrastructure), never on axe/flash/tree content.
const PORT = process.env["A11Y_PORT"] ?? "4173";
// E11-Q05 (#517): the e2e-only chart harness, built and served on its own port; the app build
// never contains it (a11y/chart-harness/, test/e2e-a11y-chart-harness.test.ts).
const HARNESS = "-c e2e/a11y/chart-harness/vite.config.ts";
export default defineConfig({
  testDir: "./a11y",
  testMatch: /.*\.collect\.ts/,
  timeout: 300_000,
  workers: 1,
  retries: 0,
  use: { baseURL: `http://127.0.0.1:${PORT}` },
  webServer: [
    {
      command: `npx vite preview --port ${PORT} --host 127.0.0.1`,
      url: `http://127.0.0.1:${PORT}`,
      reuseExistingServer: !process.env["CI"],
      cwd: "..",
      timeout: 120_000,
    },
    {
      command: `npx vite build ${HARNESS} && npx vite preview ${HARNESS} --port ${HARNESS_PORT} --host 127.0.0.1`,
      url: HARNESS_ORIGIN,
      reuseExistingServer: !process.env["CI"],
      cwd: "..",
      timeout: 120_000,
    },
  ],
});
