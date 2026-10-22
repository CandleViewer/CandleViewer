import { resolve } from "node:path";
import { defineConfig } from "vitest/config";
import { vitestPreset } from "@candleviewer/config/vitest";

// The suites import the generated rule IR module itself (the apps/web/vitest.config.mjs
// precedent), so a missing or stale protocol build never stands in for it.
const RULE_IR = resolve(import.meta.dirname, "../protocol/src/generated/ruleIr/index.ts");

// One project for now: `unit`, run under V8 coverage by test:cov. The floor is the ticket's
// engine class (E37-T01: >=85%), the same as chart-engine's (CONSTITUTION C-9.1 #4). The `perf`
// project, run without coverage, lands with the 200-node budget test (E37-T01 slice S7).
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
    ],
  },
});
