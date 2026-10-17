import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// apps/web Vite config — placeholder route only (E02-T04). Real routing,
// aliasing and env handling land in E10.
export default defineConfig({
  plugins: [react()],
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
