import { env } from "node:process";
import { defineConfig } from "vitest/config";
import { storybookTest } from "@storybook/addon-vitest/vitest-plugin";
import { vitestPreset } from "@candleviewer/config/vitest";

// Stories tagged `perf` assert a wall-clock budget, which is no pass/fail check on a shared runner
// (#269): the storybook project skips them unless CV_STORYBOOK_PERF=1 (a quiet machine only).
const perf = env["CV_STORYBOOK_PERF"] === "1";

export default defineConfig({
  test: {
    // Coverage is the unit project's (`test:cov` runs `--project unit`): stories are excluded.
    coverage: {
      ...vitestPreset.test.coverage,
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/index.ts", "src/components/index.ts", "src/**/*.stories.tsx"],
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
          environment: vitestPreset.test.environment,
          globals: vitestPreset.test.globals,
          include: ["test/**/*.test.{ts,tsx}"],
        },
      },
      {
        // E05-T03's a11y gate: each story of `.storybook/main.ts`, its play function, then axe.
        extends: true,
        plugins: [storybookTest({ configDir: ".storybook", tags: { skip: perf ? [] : ["perf"] } })],
        // Found once a story compiles; optimising it then would reload and fail a cold run.
        optimizeDeps: { include: ["react/jsx-dev-runtime"] },
        test: {
          name: "storybook",
          browser: {
            enabled: true,
            headless: true,
            provider: "playwright",
            instances: [{ browser: "chromium" }],
            // No file writes or exec through the browser API (the GHSA-82fw-gwwq-j7x9 register
            // reason). Vitest turns both on for a localhost server, and addon-vitest's own switch-off
            // reads the root config's browser block, which this projects layout leaves unset.
            api: { allowWrite: false, allowExec: false },
          },
        },
      },
    ],
  },
});
