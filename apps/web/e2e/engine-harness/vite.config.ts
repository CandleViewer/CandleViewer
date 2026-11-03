import { resolve } from "node:path";
import { mergeConfig } from "vite";
import app from "../../vite.config";

// E11-Q02 (#444, BQ-02): the harness's OWN build. It reuses the app's aliases, plugins and CSP meta,
// but its entry is this folder's index.html and its output is `dist-engine-harness/`, never `dist/`.
export default mergeConfig(app, {
  root: import.meta.dirname,
  build: { outDir: resolve(import.meta.dirname, "../../dist-engine-harness"), emptyOutDir: true },
});
