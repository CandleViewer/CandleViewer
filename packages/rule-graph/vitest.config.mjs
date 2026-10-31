import { resolve } from "node:path";
import { defineConfig } from "vitest/config";
import { vitestPreset } from "@candleviewer/config/vitest";

// The suites import the generated rule IR module itself (the apps/web/vitest.config.mjs
// precedent), so a missing or stale protocol build never stands in for it.
const RULE_IR = resolve(import.meta.dirname, "../protocol/src/generated/ruleIr/index.ts");

// Two projects: `unit`, run under V8 coverage by test:cov, and `perf` (the 200-node budget), run
// WITHOUT coverage by test:perf in the engine bench. The floor is the ticket's engine class
// (E37-T01: >=85%), the same as chart-engine's (CONSTITUTION C-9.1 #4).
export default defineConfig({
  resolve: { alias: [{ find: /^@candleviewer\/protocol\/rule-ir$/, replacement: RULE_IR }] },
  test: {
    ...vitestPreset.test,
    coverage: {
      ...vitestPreset.test.coverage,
      include: ["src/**/*.ts"],
      exclude: ["src/index.ts"],
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
