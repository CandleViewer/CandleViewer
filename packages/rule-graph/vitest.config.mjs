import { defineConfig } from "vitest/config";
import { vitestPreset } from "@candleviewer/config/vitest";

// One project for now: `unit`, run under V8 coverage by test:cov. The floor is the ticket's
// engine class (E37-T01: >=85%), the same as chart-engine's (CONSTITUTION C-9.1 #4). The `perf`
// project, run without coverage, lands with the 200-node budget test (E37-T01 slice S7).
export default defineConfig({
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
