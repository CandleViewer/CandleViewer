/**
 * Playwright config of the visual-regression suite (E05-T04, ADR-0019). `vr` compares; `vr:update` writes the
 * cells that changed beyond the tolerance or have no baseline yet, and the gate (gate.ts) refuses that in CI
 * unless the a11y workflow's `vr_update` dispatch input set VR_UPDATE=1: below on the command line, and in
 * `global-setup.ts` on the mode Playwright resolved. The capture values are settings.ts's.
 */
import { defineConfig } from "playwright/test";
import { assertUpdateAllowed } from "./gate.js";
import { PACKAGE_DIR, ORIGIN, PORT, STORYBOOK_INDEX, TOLERANCE } from "./settings.js";

assertUpdateAllowed(process.argv, process.env);

export default defineConfig({
  testDir: ".",
  testMatch: "vr.spec.ts",
  globalSetup: "./global-setup.ts",
  snapshotPathTemplate: "{testDir}/baselines/{arg}{ext}",
  outputDir: "../test-results/vr",
  // Cells, not files, are the unit of work and of `--shard`.
  fullyParallel: true,
  forbidOnly: true,
  // A diff is reported, never retried away (C-9.3).
  retries: 0,
  // One browser per two CPUs: on a saturated runner a story's commit outruns React's time slice, which
  // makes a play race its page far more often (packages/ui/README.md, Visual regression).
  workers: "50%",
  timeout: 30_000,
  updateSnapshots: "none",
  reporter: [["dot"], ["./summary-reporter.ts", { index: STORYBOOK_INDEX }]],
  expect: {
    toHaveScreenshot: { ...TOLERANCE, animations: "disabled", caret: "hide", scale: "css" },
  },
  use: { browserName: "chromium", headless: true },
  webServer: {
    command: `python3 -m http.server ${PORT} --bind 127.0.0.1 --directory storybook-static`,
    cwd: PACKAGE_DIR,
    url: `${ORIGIN}/index.json`,
    reuseExistingServer: false,
    stdout: "ignore",
    stderr: "ignore",
  },
});
