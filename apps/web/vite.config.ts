import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `CV_ALLOW_FAULT_INJECTION=1` builds the dev-only WS fault-injection channel into the shared worker (E17-T04 S5e).
// Without it the flag is `false`, `import.meta.env.DEV` is `false` in a production build, and the channel is not bundled.
const allowFaultInjection = process.env["CV_ALLOW_FAULT_INJECTION"] === "1";

// apps/web Vite config — placeholder route only (E02-T04). Real routing,
// aliasing and env handling land in E10.
export default defineConfig({
  plugins: [react()],
  define: { __CV_ALLOW_FAULT_INJECTION__: JSON.stringify(allowFaultInjection) },
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
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
