// E11-Q05 (#517): builds the e2e-only chart harness (index.html here) with the app's own aliases
// and defines, into its own outDir under node_modules/.cache (ignored by git, eslint and prettier). The app's `vite build` never sees this entry: its root is
// apps/web and its only input is apps/web/index.html (test/e2e-a11y-chart-harness.test.ts).
import { resolve } from "node:path";
import { defineConfig, mergeConfig, type UserConfig } from "vite";
import app from "../../../vite.config";

export const HARNESS_OUT_DIR = resolve(
  import.meta.dirname,
  "../../../node_modules/.cache/cv-chart-harness",
);

const config: UserConfig = mergeConfig(
  app,
  defineConfig({
    root: import.meta.dirname,
    build: { outDir: HARNESS_OUT_DIR, emptyOutDir: true },
    preview: { strictPort: true },
  }),
);

export default config;
