import { defineConfig } from "vitest/config";
import { vitestPreset } from "@candleviewer/config/vitest";

// One `unit` project, run under V8 coverage by test:cov. The floor is the ticket's engine class
// (E15-T02 DoD: >=85%), the same as chart-engine's (CONSTITUTION C-9.1 #4).
export default defineConfig({
  test: {
    ...vitestPreset.test,
    include: ["test/**/*.test.ts"],
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
  },
});
