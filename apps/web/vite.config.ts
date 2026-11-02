import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `CV_ALLOW_FAULT_INJECTION=1` builds the dev-only WS fault-injection channel into the shared worker (E17-T04 S5e).
// Without it the flag is `false`, `import.meta.env.DEV` is `false` in a production build, and the channel is not bundled.
const allowFaultInjection = process.env["CV_ALLOW_FAULT_INJECTION"] === "1";
// `CV_MFA_RECOVERY_UI=1` builds SCR-002's recovery-code form (#2711 BQ-08 (a)). Off by default, so a production
// build has it `false` and the form is not bundled: a recovery sign-in lands on enrolment (R-006), not built yet.
const mfaRecoveryUi = process.env["CV_MFA_RECOVERY_UI"] === "1";

// The status bar's version (E10-S01 S4): this package's `version`, fixed at build time.
const pkg = JSON.parse(readFileSync(resolve(import.meta.dirname, "package.json"), "utf8")) as {
  readonly version: string;
};

// apps/web Vite config — placeholder route only (E02-T04). Real routing,
// aliasing and env handling land in E10.
export default defineConfig({
  plugins: [react()],
  define: {
    __CV_ALLOW_FAULT_INJECTION__: JSON.stringify(allowFaultInjection),
    __CV_APP_VERSION__: JSON.stringify(pkg.version),
    __CV_MFA_RECOVERY_UI__: JSON.stringify(mfaRecoveryUi),
  },
  // The shared worker is an ES module, so it can `import()` the fault channel and share chunks with the app.
  worker: { format: "es" },
  resolve: {
    alias: [
      // Exact match for the entry only: `@candleviewer/ui/theme.css` and the token CSS must resolve through
      // the package `exports` (built files), not turn into `src/index.ts/theme.css`.
      {
        find: /^@candleviewer\/ui$/,
        replacement: resolve(import.meta.dirname, "../../packages/ui/src/index.ts"),
      },
      // The root is the §8 surface; `/compat` is the pre-§8 palette/flags seam (E11-T01 BQ-2).
      {
        find: /^@candleviewer\/chart-engine$/,
        replacement: resolve(import.meta.dirname, "../../packages/chart-engine/src/index.ts"),
      },
      {
        find: /^@candleviewer\/chart-engine\/compat$/,
        replacement: resolve(import.meta.dirname, "../../packages/chart-engine/src/compat.ts"),
      },
      {
        find: /^@candleviewer\/dock$/,
        replacement: resolve(import.meta.dirname, "../../packages/dock/src/index.ts"),
      },
      {
        find: "@candleviewer/protocol",
        replacement: resolve(import.meta.dirname, "../../packages/protocol/src/index.ts"),
      },
    ],
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
