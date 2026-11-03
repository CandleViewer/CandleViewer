import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

// Playwright resolves a reporter `outputFile` against this file's directory (e2e/); anchor the JSON
// report to the package root, where CI's flaky-summary step reads it (E10-Q02).
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FLAKY = /@flaky/u;
const QUARANTINE = process.env["CV_E2E_QUARANTINE"] === "1";
// E49-Q01 (#1335): the GA regression pack, `@ga-regression` tests only (tools/ga/specs.py reads
// the same tags). Its project exists only when CV_E2E_GA=1 (ga-regression-nightly.yml, or a local
// `CV_E2E_GA=1 pnpm exec playwright test -c e2e/playwright.config.ts --project=ga-regression`), so
// the PR lane never runs a pack test twice. A `@flaky` pack test stays in the quarantine leg.
// The pack runs with zero retries (#1335 ruling), so a flaky pack test fails its night; the
// global CI retry below vs 03 section 14 is carried to the CI owner (#569 BQ-10).
const GA = /@ga-regression/u;
const PACK = process.env["CV_E2E_GA"] === "1";
// The pack's own specs (e2e/ga/: the admin RBAC negatives and the carried stubs) run in the pack
// project only, so the PR lane runs exactly the specs it ran before the pack existed.
const GA_ONLY = /[\\/]e2e[\\/]ga[\\/]/u;

// apps/web Playwright config — smoke + a11y specs only (E02-T04).
export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  // E03-T06: one automatic retry in CI (each retry recorded in the reporter
  // output for E03-Q03's deferred quarantine automation); local runs stay
  // deterministic (no retry) so failures aren't masked during development.
  retries: process.env["CI"] ? 1 : 0,
  // E10-Q02 / C-9.3: a test tagged `@flaky` is quarantined, never silently skipped: the PR lane's
  // project drops it (grepInvert) and e2e-nightly.yml runs it in the `flaky-nightly` project
  // (CV_E2E_QUARANTINE=1). It carries a P1 ticket and is fixed or deleted within 10 working days.
  projects: QUARANTINE
    ? [{ name: "flaky-nightly", grep: FLAKY }]
    : PACK
      ? [{ name: "ga-regression", grep: GA, grepInvert: FLAKY, retries: 0 }]
      : [{ name: "chromium", grepInvert: FLAKY, testIgnore: GA_ONLY }],
  // The JSON report next to the list: CI writes its `stats.flaky` count (passed only on retry) to
  // the job summary, so a pass-on-retry is visible on the PR (E10-Q02).
  reporter: [
    ["list"],
    ["json", { outputFile: path.resolve(__dirname, "../playwright-report/results.json") }],
  ],
  // E03-T06-B1 (bug #1527): capture failure artifacts so AC3's
  // "trace/video/screenshot uploaded on failure" scenario is actually
  // satisfied — defaults are "off"; "on-first-retry" / "retain-on-failure"
  // only materialize files when a spec actually fails.
  use: {
    baseURL: "http://127.0.0.1:4173",
    // E10-Q02: retain-on-failure, not on-first-retry, so a first failure keeps its trace even
    // when the retry passes. Stub values only: no real session is ever captured.
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: "npx vite preview --port 4173 --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env["CI"],
    cwd: "..",
    timeout: 120_000,
  },
});
