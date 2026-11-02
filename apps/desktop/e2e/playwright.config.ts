import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

// Playwright resolves a relative webServer.cwd against this file's directory (e2e/), not the
// package root: "../web" named a missing apps/desktop/web (#3366). Anchor it to apps/web.
const __dirname = path.dirname(fileURLToPath(import.meta.url));

// apps/desktop Playwright-Electron config (E02-T04): hardening assertion +
// main-window smoke specs.
// E10-Q02: the packaged smoke runs in its own project, only when CI has built the package and
// names its executable; every other spec runs on the unpacked `dist/`.
const PACKAGED = /packaged-smoke\.spec\.ts$/u;
const FLAKY = /@flaky/u;
const QUARANTINE = process.env["CV_E2E_QUARANTINE"] === "1";
// E49-Q01 (#1335): the GA regression pack's Electron lane, as apps/web's config: `@ga-regression`
// tests only, and only when CV_E2E_GA=1, so the PR lane runs nothing twice. The packaged project
// joins when CI has built the package, so the shell-specific paths run on the shipped binary.
const GA = /@ga-regression/u;
const PACK = process.env["CV_E2E_GA"] === "1";
const HAS_PACKAGE = Boolean(process.env["CV_PACKAGED_EXECUTABLE"]);
// The pack's own specs (ga-*.spec.ts: the carried stubs) run in the pack project only, so the PR
// lane's `dist` project runs exactly the specs it ran before the pack existed.
const GA_ONLY = /(?:^|[\\/])ga-[^\\/]*\.spec\.ts$/u;

export default defineConfig({
  testDir: ".",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  // outputFile resolves against e2e/ too: anchor it to the package root, where flaky-summary reads it.
  reporter: [
    ["list"],
    ["json", { outputFile: path.resolve(__dirname, "../playwright-report/results.json") }],
  ],
  // C-9.3 quarantine, as apps/web's config: the PR lane's projects drop a `@flaky` test and
  // e2e-nightly.yml runs it in `flaky-nightly` (CV_E2E_QUARANTINE=1) until it is fixed or deleted.
  projects: QUARANTINE
    ? [{ name: "flaky-nightly", grep: FLAKY, testIgnore: PACKAGED }]
    : PACK
      ? [
          { name: "ga-regression", testIgnore: PACKAGED, grep: GA, grepInvert: FLAKY },
          ...(HAS_PACKAGE
            ? [{ name: "ga-regression-packaged", testMatch: PACKAGED, grep: GA, grepInvert: FLAKY }]
            : []),
        ]
      : [
          { name: "dist", testIgnore: [PACKAGED, GA_ONLY], grepInvert: FLAKY },
          ...(HAS_PACKAGE ? [{ name: "packaged", testMatch: PACKAGED, grepInvert: FLAKY }] : []),
        ],
  // E03-T06-B1 (bug #1527): capture failure artifacts (AC3). No retries
  // configured here, so "on-first-retry" would never fire — use
  // "retain-on-failure" for trace too so a single failed run still uploads.
  // hotkeys.spec.ts loads the built web app via CV_DEV_SERVER_URL; serve it with `vite preview`
  // (requires `pnpm --filter @candleviewer/web build` first, as the web e2e job does).
  webServer: {
    command: "npx vite preview --port 4173 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env["CI"],
    cwd: path.resolve(__dirname, "../../web"),
    timeout: 120_000,
  },
  use: {
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
});
