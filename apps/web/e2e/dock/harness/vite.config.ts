import { resolve } from "node:path";
import { defineConfig, mergeConfig } from "vite";
import base from "../../../vite.config";

// E15-T02 (#403): the e2e-only DockGrid harness build, the app's own config (aliases, defines,
// module worker) rooted at this folder and written under the git-ignored test-results/. The spec
// builds and previews it on a loopback port; the production `dist/` never contains it.
export const HARNESS_OUT = resolve(import.meta.dirname, "../../../test-results/dock-harness-dist");

export default mergeConfig(
  base,
  defineConfig({
    root: import.meta.dirname,
    base: "./",
    logLevel: "warn",
    build: { outDir: HARNESS_OUT, emptyOutDir: true, sourcemap: false },
    preview: { host: "127.0.0.1", strictPort: true },
  }),
);
