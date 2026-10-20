// @vitest-environment node
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { build } from "tsup";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { componentName } from "../../scripts/build-icons.mjs";
import { ICONS, type IconName } from "../../src/icons/registry.js";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
// Object.keys widens to string[]; ICONS' keys are exactly IconName, the type derived from them.
const NAMES = Object.keys(ICONS) as IconName[];
/** The ticket's performance note: the icons of a typical screen add at most 15 KB gzipped. */
const BUDGET_GZIP_BYTES = 15 * 1024;
const USED: readonly IconName[] = ["check", "close", "search"];
let outDir = "";

/** Bundles `code` as an app's entry with tsup (esbuild), React external; returns the output. */
async function bundle(name: string, code: string): Promise<string> {
  const entry = path.join(outDir, `${name}-entry.ts`);
  writeFileSync(entry, code);
  await build({
    entry: { [name]: entry },
    outDir,
    format: ["esm"],
    platform: "browser",
    target: "es2022",
    external: ["react", "react-dom", "react/jsx-runtime"],
    tsconfig: path.join(PACKAGE, "tsconfig.json"),
    config: false,
    dts: false,
    sourcemap: false,
    splitting: false,
    minify: false,
    clean: false,
    silent: true,
  });
  const [output = ""] = readdirSync(outDir).filter(
    (file) => /^[\w-]+\.m?js$/.test(file) && file.startsWith(`${name}.`),
  );
  return readFileSync(path.join(outDir, output), "utf-8");
}

const from = (module: string) => JSON.stringify(path.join(PACKAGE, "src", module));
const defines = (output: string, name: IconName) =>
  output.includes(`function ${componentName(name)}(`);

beforeAll(() => {
  outDir = mkdtempSync(path.join(tmpdir(), "cv-icons-"));
});
afterAll(() => rmSync(outDir, { recursive: true, force: true }));

describe("icon tree-shaking (E05-T06 Gherkin: an app importing three icons)", () => {
  it("bundles the three icons an app imports from the package, and no other", async () => {
    const output = await bundle(
      "three",
      `export { CheckIcon, CloseIcon, SearchIcon } from ${from("index.ts")};`,
    );
    expect(NAMES.filter((name) => defines(output, name))).toEqual(USED);
    // Nor does the registry come along: no icon's description is in the bundle.
    expect(NAMES.filter((name) => output.includes(ICONS[name].description))).toEqual([]);
  }, 60_000);

  it("keeps even the whole base set within a screen's 15 KB gzipped budget", async () => {
    const output = await bundle(
      "all",
      `export { ICON_COMPONENTS } from ${from("icons/generated/components.ts")};`,
    );
    expect(NAMES.filter((name) => !defines(output, name))).toEqual([]);
    expect(gzipSync(output).byteLength).toBeLessThanOrEqual(BUDGET_GZIP_BYTES);
  }, 60_000);
});
