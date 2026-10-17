import { defineConfig } from "tsup";

export default defineConfig({
  entry: { index: "src/index.ts" },
  format: ["esm"],
  dts: true,
  sourcemap: true,
  clean: true,
  target: "es2022",
  platform: "browser",
  external: ["react", "react-dom"],
  // The CSS apps import (`theme.css`, the token CSS) is copied next to the JS entry; see the exports map.
  onSuccess: "node scripts/copy-css.mjs",
});
