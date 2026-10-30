// The GL-object ownership rule (E11-S02 Scope, README BQ-57): only src/gl/registry.ts creates GL
// objects, and no module outside src/gl names the registry's `Handle` brand, so a context loss
// can invalidate and recreate everything in one place. Each matcher is first proven to bite on
// an in-memory fixture, so a later edit cannot quietly blunt it.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const PKG = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
// Any mention of a create method except a bare `createX(): …` declaration: dotted, bracketed or
// destructured calls all count.
const CREATE = /\bcreate(?:Buffer|Texture|Program|VertexArray)\b(?!\s*\(\)\s*:)/;
// A named import from src/gl (a module in it or its index), or an inline `import("…/gl…").Handle`.
const GL_PATH = String.raw`["'][^"']*\/gl(?:\/[^"']*)?["']`;
const BRAND = new RegExp(
  String.raw`import\s+(?:type\s+)?\{[^}]*\bHandle\b[^}]*\}\s*from\s*${GL_PATH}` +
    String.raw`|import\(\s*${GL_PATH}\s*\)\s*\.\s*Handle\b`,
);

function sources(dir: string): [string, string][] {
  return readdirSync(join(PKG, dir), { recursive: true, encoding: "utf8" })
    .filter((f) => /\.(?:ts|mts|mjs)$/.test(f))
    .map((f) => [relative(PKG, join(PKG, dir, f)), readFileSync(join(PKG, dir, f), "utf8")]);
}
// The engine and its bench scenes; bench/matrix is the spike-only page harness that never loads
// the engine (E06-T01), so its own throwaway GL probes are out of scope.
const all = [...sources("src"), ...sources("bench/scenes")];

describe("the GL-object ownership rule", () => {
  it("the matchers bite on in-memory fixtures", () => {
    expect(CREATE.test("const b = gl.createBuffer();")).toBe(true);
    expect(CREATE.test("const v = this.gl.createVertexArray ();")).toBe(true);
    expect(CREATE.test('const t = gl["createTexture"]();')).toBe(true);
    expect(CREATE.test("const { createProgram } = gl;")).toBe(true);
    expect(CREATE.test("createBuffer(): GLObject | null;")).toBe(false); // a declaration
    expect(BRAND.test('import { type Handle } from "../gl/registry.js";')).toBe(true);
    expect(
      BRAND.test('import type {\n  GlRegistry,\n  Handle,\n} from "../../src/gl/index.js";'),
    ).toBe(true);
    expect(BRAND.test('import type { Handle } from "../gl";')).toBe(true);
    expect(BRAND.test('let h: import("../gl/registry.js").Handle<"buffer">;')).toBe(true);
    expect(BRAND.test('import { GlRegistry } from "../gl/registry.js";')).toBe(false);
    expect(BRAND.test('import { type Handle } from "../glyph/atlas.js";')).toBe(false);
  });

  it("only src/gl/registry.ts calls create{Buffer,Texture,Program,VertexArray}", () => {
    const callers = all.filter(([, text]) => CREATE.test(text)).map(([path]) => path);
    expect(callers).toEqual(["src/gl/registry.ts"]);
  });

  it("no module outside src/gl imports the handle brand", () => {
    const outside = all.filter(([path, text]) => !path.startsWith("src/gl/") && BRAND.test(text));
    expect(outside.map(([path]) => path)).toEqual([]);
  });
});
