import { defineConfig } from "vitest/config";
import { vitestPreset } from "@candleviewer/config/vitest";

// Two projects (the rule-graph precedent): `unit`, run under V8 coverage by test:cov, and `perf`
// (the ticket's 10 ms irToForm / formToIr budget on the 100-node fixture, which lands with the IR
// adapter), run WITHOUT coverage by test:perf. The floor is the ticket's: 90 % lines, above the
// 80 % frontend floor because the package carries the round-trip guarantee (C-9.4 lets a floor
// rise without an amendment), and the frontend lane's 75 % branches.
export default defineConfig({
  test: {
    ...vitestPreset.test,
    coverage: {
      ...vitestPreset.test.coverage,
      include: ["src/**/*.ts"],
      // index.ts re-exports and model.ts is types only: neither has a line to cover.
      exclude: ["src/index.ts", "src/model.ts"],
      thresholds: {
        lines: 90,
        statements: 90,
        functions: 90,
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
