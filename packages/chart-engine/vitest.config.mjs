import { defineConfig } from "vitest/config";
import { vitestPreset } from "@candleviewer/config/vitest";

// Two projects: `unit` (run under V8 coverage by test:cov) and `perf` (wall-clock budgets,
// run WITHOUT coverage by engine-bench: instrumentation inflates timings).
export default defineConfig({
  test: {
    ...vitestPreset.test,
    coverage: {
      ...vitestPreset.test.coverage,
      include: ["src/**/*.ts", "bench/**/*.ts", "bench/**/*.mjs"],
      exclude: [
        "src/**/index.ts",
        "bench/run-bench.mjs",
        "bench/scenes/run-scene-*.mjs",
        // E06-T01: process/browser-only entry points (same rationale as the CLIs above):
        // exercised by the owner's reference-machine run, not by unit tests.
        "bench/matrix/run-matrix.mjs",
        "bench/matrix/page/**",
        "bench/matrix/electron/main.cjs",
        "bench/matrix/electron/preload.cjs",
        "bench/matrix/fixture-digest.mjs",
      ],
      // Constitution §9 #4: chart-engine coverage floor is >=85%.
      thresholds: {
        lines: 85,
        statements: 85,
        functions: 85,
        branches: 75,
      },
    },
    projects: [
      {
        extends: true,
        test: {
          name: "unit",
          include: ["test/**/*.test.ts"],
          exclude: ["test/**/*.perf.test.ts"],
        },
      },
      {
        extends: true,
        test: {
          name: "perf",
          include: ["test/**/*.perf.test.ts"],
          testTimeout: 60_000,
          // C-9.3: a wall-clock budget may retry twice on the shared runner; the budget never moves.
          retry: 2,
          setupFiles: ["../config/src/perf-calibration-setup.mjs"],
        },
      },
    ],
  },
});
