import { resolve } from "node:path";
import process from "node:process";
import { defaultClientConditions } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { vitestPreset } from "@candleviewer/config/vitest";

export default defineConfig({
  plugins: [react()],
  // The WS fault-injection flag (E17-T04 S5e): off unless CV_ALLOW_FAULT_INJECTION=1, as in vite.config.ts.
  define: {
    __CV_ALLOW_FAULT_INJECTION__: JSON.stringify(process.env.CV_ALLOW_FAULT_INJECTION === "1"),
  },
  resolve: {
    // Vite's own conditions plus `module-sync` (Node >= 20.19), which points `react-router` and
    // `react-router/dom` at one ESM build: the dom entry and the app share one router copy, so
    // error elements keep their router context.
    conditions: [...defaultClientConditions, "module-sync"],
    alias: [
      // Exact match for the entry only: `@candleviewer/ui/theme.css` and the token CSS must resolve through
      // the package `exports` (built files), not turn into `src/index.ts/theme.css`.
      {
        find: /^@candleviewer\/ui$/,
        replacement: resolve(import.meta.dirname, "../../packages/ui/src/index.ts"),
      },
      {
        find: "@candleviewer/chart-engine",
        replacement: resolve(import.meta.dirname, "../../packages/chart-engine/src/index.ts"),
      },
      {
        find: "@candleviewer/protocol",
        replacement: resolve(import.meta.dirname, "../../packages/protocol/src/index.ts"),
      },
    ],
  },
  test: {
    ...vitestPreset.test,
    coverage: {
      ...vitestPreset.test.coverage,
      // #1535: do not wipe coverage/ at start (it raced the .tmp writer on a cold
      // cache); the test:cov script pre-creates coverage/.tmp instead.
      clean: false,
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/main.tsx", "src/**/*.stories.tsx", "src/shell/ShellPort.ts"],
      thresholds: {
        lines: 80,
        statements: 80,
        functions: 80,
        branches: 70,
      },
    },
    // Two projects: `unit` (the default run, under V8 coverage) and `fuzz` (#415: the nightly
    // mutation fuzz of the WS codec; no PR lane runs it). Each names its own `include`: with
    // `extends: true` a root-level one would be concatenated into both.
    projects: [
      {
        extends: true,
        test: {
          name: "unit",
          environment: "jsdom",
          setupFiles: ["./test/setup.ts"],
          include: ["test/**/*.test.{ts,tsx}"],
          exclude: ["test/**/*.fuzz.test.ts"],
        },
      },
      {
        extends: true,
        test: { name: "fuzz", include: ["test/**/*.fuzz.test.ts"], testTimeout: 600_000 },
      },
    ],
  },
});
