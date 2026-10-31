import { defineConfig } from "vitest/config";
import { vitestPreset } from "@candleviewer/config/vitest";

// Three projects: `unit` (default `test`, run under V8 coverage), `perf` (decode budgets, run
// WITHOUT coverage by the bench lane) and `fuzz` (E17-T02 nightly mutation fuzz, nightly only).
export default defineConfig({
  test: {
    ...vitestPreset.test,
    coverage: {
      ...vitestPreset.test.coverage,
      include: ["src/**/*.ts"],
      exclude: ["src/index.ts", "src/generated/**"],
      thresholds: {
        lines: 80,
        statements: 80,
        functions: 80,
        branches: 70,
      },
    },
    projects: [
      {
        extends: true,
        test: {
          name: "unit",
          include: ["test/**/*.test.{ts,mjs}"],
          exclude: ["test/**/*.perf.test.ts", "test/**/*.fuzz.test.ts"],
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
      {
        extends: true,
        test: { name: "fuzz", include: ["test/**/*.fuzz.test.ts"], testTimeout: 600_000 },
      },
    ],
  },
});
