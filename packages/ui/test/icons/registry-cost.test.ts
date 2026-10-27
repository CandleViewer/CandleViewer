import { spawnSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { ICON_FORMS } from "../../src/icons/generated/components.js";
import { ICONS, type IconName } from "../../src/icons/registry.js";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
// Object.keys widens to string[]; ICONS' keys are exactly IconName, the type derived from them.
const NAMES = Object.keys(ICONS) as IconName[];
/** E05-T06's amended criterion: the whole registry, through the by-name `Icon`, 15 KB gzipped. */
const BOUND = 15 * 1024;
/**
 * The icon entry alone, as an app's production build takes it: minified ESM for the browser, React
 * left to the app. Not the package's tsup.config.ts, which builds every entry with source maps.
 */
const OPTIONS = {
  config: false,
  entry: { icons: "src/icons/index.ts" },
  format: ["esm"],
  platform: "browser",
  target: "es2022",
  minify: true,
  splitting: false,
  dts: false,
  sourcemap: false,
  external: ["react", "react/jsx-runtime"],
  silent: true,
};
/** tsup (esbuild) with `OPTIONS`, into argv[1]. */
const BUILD =
  'const { build } = await import("tsup");\n' +
  `await build({ ...${JSON.stringify(OPTIONS)}, outDir: process.argv[1] });`;

// `Icon` imports every glyph by name (CMP-019), so no app tree-shakes one away: the bound is on the
// whole registry. The entry keeps all its exports, `ICONS` and its descriptions too, so the measure
// is an upper bound on what an app pays.
describe("the icon registry's cost in a production bundle (src/icons/index.ts)", () => {
  it("adds at most 15 KB gzipped, every glyph and size form included", { timeout: 60_000 }, () => {
    const outDir = mkdtempSync(path.join(tmpdir(), "cv-icon-cost-"));
    try {
      const built = spawnSync(process.execPath, ["--input-type=module", "-e", BUILD, outDir], {
        cwd: PACKAGE,
        encoding: "utf-8",
        // Under the test's own 60 s, which can't pre-empt a synchronous child.
        timeout: 50_000,
        killSignal: "SIGKILL",
      });
      expect(built.status, String(built.error ?? built.stderr)).toBe(0);
      // One file, so the measure is the whole cost: no chunk, map or declaration beside it.
      expect(readdirSync(outDir)).toEqual(["icons.js"]);
      const bundle = readFileSync(path.join(outDir, "icons.js"), "utf-8");
      // React stays the app's: the bundle imports the production JSX runtime and nothing else.
      const imports = [...bundle.matchAll(/\bfrom\s*"([^"]+)"/g)].map(([, from]) => from);
      expect(new Set(imports)).toEqual(new Set(["react/jsx-runtime"]));
      // Each glyph module, size forms included, hands the grid its registry name as `icon`.
      const drawn = [...bundle.matchAll(/\bicon:"([\da-z-]+)"/g)].map(([, name]) => name);
      const forms: Partial<Record<IconName, object>> = ICON_FORMS;
      const modules = NAMES.flatMap((name) => [
        name,
        ...Object.keys(forms[name] ?? {}).map(() => name),
      ]);
      expect(drawn.sort()).toEqual(modules.sort());
      // gzip at zlib's default level.
      const gzipped = gzipSync(bundle).length;
      expect(gzipped, `${gzipped} bytes gzipped`).toBeLessThanOrEqual(BOUND);
    } finally {
      rmSync(outDir, { recursive: true, force: true });
    }
  });
});
