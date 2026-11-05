import { defineConfig } from "vitest/config";
import { vitestPreset } from "@candleviewer/config/vitest";

// Two projects (the rule-graph precedent): `unit`, run under V8 coverage by test:cov, and `perf`
// (the 8 ms p95 recompute budget, `14` SCR-060, lands with slice S4), run WITHOUT coverage by
// test:perf. The floor is BQ 9 of #984: 95 % lines / 85 % branches, above the engine class
// (C-9.4 lets a floor rise without an amendment).
export default defineConfig({
  test: {
    ...vitestPreset.test,
    coverage: {
      ...vitestPreset.test.coverage,
      include: ["src/**/*.ts"],
      exclude: ["src/index.ts"],
      thresholds: {
        lines: 95,
        statements: 95,
        functions: 95,
        branches: 85,
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
