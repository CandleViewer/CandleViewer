import { defineConfig } from "vitest/config";
import { vitestPreset } from "@candleviewer/config/vitest";

export default defineConfig({
  test: {
    ...vitestPreset.test,
    // E10-Q02: `test/e2e/` unit-tests the pure helpers of the `e2e` subpath (the CSP parser, the
    // route classifier); its Playwright helpers run in the web and Electron suites that import them.
    include: ["test/**/*.test.mjs", "test/**/*.test.ts"],
    coverage: {
      ...vitestPreset.test.coverage,
      include: ["src/**/*.mjs", "scripts/**/*.mjs"],
      exclude: ["src/index.mjs"],
    },
  },
});
