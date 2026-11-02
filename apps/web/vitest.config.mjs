import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import process from "node:process";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { vitestPreset } from "@candleviewer/config/vitest";

export default defineConfig({
  plugins: [react()],
  // The WS fault-injection flag (E17-T04 S5e): off unless CV_ALLOW_FAULT_INJECTION=1, as in vite.config.ts.
  define: {
    __CV_ALLOW_FAULT_INJECTION__: JSON.stringify(process.env.CV_ALLOW_FAULT_INJECTION === "1"),
    // SCR-002's recovery-code form (#2711 BQ-08 (a)): off unless CV_MFA_RECOVERY_UI=1, as in vite.config.ts.
    __CV_MFA_RECOVERY_UI__: JSON.stringify(process.env.CV_MFA_RECOVERY_UI === "1"),
    // The status bar's version (E10-S01 S4), as in vite.config.ts.
    __CV_APP_VERSION__: JSON.stringify(
      JSON.parse(readFileSync(resolve(import.meta.dirname, "package.json"), "utf8")).version,
    ),
  },
  resolve: {
    // Vitest resolves this jsdom project with node-style conditions, where react-router's `node`
    // export falls through to its CommonJS `default` while the dom entry's own import loads ESM
    // via `module-sync`: two router copies. Adding `module-sync` selects the ESM build for both.
    conditions: ["module-sync"],
    alias: [
      // Exact match for the entry only: `@candleviewer/ui/theme.css` and the token CSS must resolve through
      // the package `exports` (built files), not turn into `src/index.ts/theme.css`.
      {
        find: /^@candleviewer\/ui$/,
        replacement: resolve(import.meta.dirname, "../../packages/ui/src/index.ts"),
      },
      // The root is the §8 surface; `/compat` is the pre-§8 palette/flags seam (E11-T01 BQ-2).
      {
        find: /^@candleviewer\/chart-engine$/,
        replacement: resolve(import.meta.dirname, "../../packages/chart-engine/src/index.ts"),
      },
      {
        find: /^@candleviewer\/chart-engine\/compat$/,
        replacement: resolve(import.meta.dirname, "../../packages/chart-engine/src/compat.ts"),
      },
      {
        find: /^@candleviewer\/dock$/,
        replacement: resolve(import.meta.dirname, "../../packages/dock/src/index.ts"),
      },
      {
        find: "@candleviewer/protocol",
        replacement: resolve(import.meta.dirname, "../../packages/protocol/src/index.ts"),
      },
    ],
  },
  test: {
    ...vitestPreset.test,
    coverage: {
      ...vitestPreset.test.coverage,
      // #1535: do not wipe coverage/ at start (it raced the .tmp writer on a cold
      // cache); the test:cov script pre-creates coverage/.tmp instead.
      clean: false,
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/main.tsx", "src/**/*.stories.tsx", "src/shell/ShellPort.ts"],
      thresholds: {
        lines: 80,
        statements: 80,
        functions: 80,
        branches: 70,
      },
    },
    // Three projects: `unit` (the default run, under V8 coverage), `perf` (E15-T02's wall-clock
    // budgets, no coverage) and `fuzz` (#415: the nightly mutation fuzz of the WS codec; no PR lane
    // runs it). Each names its own `include`: with `extends: true` a root-level one would be
    // concatenated into every project.
    projects: [
      {
        extends: true,
        test: {
          name: "unit",
          environment: "jsdom",
          setupFiles: ["./test/setup.ts"],
          include: ["test/**/*.test.{ts,tsx}"],
          exclude: ["test/**/*.fuzz.test.ts", "test/**/*.perf.test.{ts,tsx}"],
        },
      },
      {
        // E15-T02: wall-clock budgets (the dock's preset apply and panel mount), WITHOUT coverage.
        extends: true,
        test: {
          name: "perf",
          environment: "jsdom",
          setupFiles: ["./test/setup.ts", "../../packages/config/src/perf-calibration-setup.mjs"],
          include: ["test/**/*.perf.test.{ts,tsx}"],
          testTimeout: 60_000,
          // C-9.3: a wall-clock budget may retry twice on the shared runner; the budget never moves.
          retry: 2,
        },
      },
      {
        extends: true,
        test: { name: "fuzz", include: ["test/**/*.fuzz.test.ts"], testTimeout: 600_000 },
      },
    ],
  },
});
