import { defineConfig } from "tsup";

// tsup build: ESM only, workspace-consumable, semver'd per docs/plan/20-architecture.md §7.
export default defineConfig({
  entry: {
    index: "src/index.ts",
    compat: "src/compat.ts",
    // The render worker is its own same-origin module (no `blob:` URL; E11-T02, E10 CSP): the
    // host loads it as `new URL("./render-worker.js", import.meta.url)`.
    "render-worker": "src/worker/render-worker.ts",
    bench: "bench/harness.ts",
  },
  format: ["esm"],
  // tsconfig.json is solution-style; build against the no-DOM program (C-2.16 guard for
  // core/layers). The public types name `HTMLElement`, so the declaration build gets the DOM lib,
  // as tsconfig.dom.json does.
  tsconfig: "tsconfig.core.json",
  dts: { compilerOptions: { lib: ["ES2022", "DOM"] } },
  sourcemap: true,
  clean: true,
  target: "es2022",
  platform: "neutral",
});
