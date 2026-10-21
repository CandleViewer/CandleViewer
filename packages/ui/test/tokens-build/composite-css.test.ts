// @vitest-environment node
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { transform } from "esbuild";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { failedBuildOutput, makeSandbox, runBuild } from "./sandbox.js";

type Token = { $type: string; $value: unknown };
type Theme = Record<string, Token>;

// The resolved themes come from the token sources through the build's own loader (as the contrast
// gate and label-on-fill.test.ts use it); the names the bundles must define are derived from them.
const build = (await import(/* @vite-ignore */ "../../scripts/build-tokens.mjs" as string)) as {
  loadResolvedThemes(): Promise<Record<string, Theme>>;
};
const themes = await build.loadResolvedThemes();

const property = (name: string) => `--${name.replaceAll(".", "-")}`;
const kebab = (field: string) => field.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);

/** What a theme's bundle must define for each composite (shadow, typography) token of its sources. */
function composites(theme: Theme) {
  const shadows: string[] = [];
  const typography: { whole: string; parts: string[] }[] = [];
  for (const [name, token] of Object.entries(theme)) {
    if (token.$type === "shadow") shadows.push(property(name));
    if (token.$type === "typography") {
      // A typography value is an object of CSS-property-like fields once its references are resolved.
      const fields = Object.keys(token.$value as object);
      const parts = fields.map((field) => `${property(name)}-${kebab(field)}`);
      typography.push({ whole: property(name), parts });
    }
  }
  return { shadows, typography };
}

/** The `--name: value;` declarations of a generated file, in order (one per line). */
function declarations(css: string): [string, string][] {
  const found = css.matchAll(/^[ \t]*(--[\w-]+):[ \t]*(.*);$/gm);
  return [...found].map(([, name = "", value = ""]) => [name, value]);
}

/** The same declarations as esbuild's minifier prints them: `{--a: 1;--b:;--c: 2}`. */
function minifiedDeclarations(code: string): [string, string][] {
  const found = code.matchAll(/(?:^|[{;])(--[\w-]+):([^;{}]*)/g);
  return [...found].map(([, name = "", value = ""]) => [name, value.trim()]);
}

/** What sits between the first `{` and the first `}`: the `[data-theme]` block, before any mode block. */
const themeBlock = (css: string) => css.slice(css.indexOf("{") + 1, css.indexOf("}"));

// A box-shadow list as the build writes it: `[inset ]<x> <y> <blur> <spread> <colour>`, lengths in px.
const LAYER = String.raw`(?:inset )?(?:-?[\d.]+px ){4}#[0-9A-Fa-f]{6,8}`;
const SHADOW = new RegExp(`^${LAYER}(?:, ${LAYER})*$`);

describe("generated token CSS: composite tokens (shadow, typography)", () => {
  const generated = new Map<string, { source: string; code: string; warnings: string[] }>();
  let sandbox = "";
  beforeAll(async () => {
    sandbox = makeSandbox();
    const ui = path.join(sandbox, "packages", "ui");
    runBuild(ui);
    for (const theme of Object.keys(themes)) {
      const source = readFileSync(path.join(ui, "build", "css", `tokens.${theme}.css`), "utf-8");
      // The production bundle minifies CSS with esbuild (Vite's default `cssMinify`), so this does too.
      const minified = await transform(source, { loader: "css", minify: true, logLevel: "silent" });
      const warnings = minified.warnings.map(({ location, text }) => `${location?.line}: ${text}`);
      generated.set(theme, { source, code: minified.code, warnings });
    }
  }, 60_000);
  afterAll(() => {
    rmSync(sandbox, { recursive: true, force: true });
  });

  it("covers the three themes of the build", () => {
    expect(Object.keys(themes)).toEqual(["dark", "light", "high-contrast"]);
  });

  describe.each(Object.keys(themes))("the %s bundle", (theme) => {
    const bundle = () => {
      const found = generated.get(theme);
      if (!found) throw new Error(`no token CSS was built for the ${theme} theme`);
      return found;
    };

    it("minifies without a warning", () => {
      expect(bundle().warnings).toEqual([]);
    });

    it("keeps every custom property of its theme block through minification, none empty", () => {
      const { source, code } = bundle();
      const kept = minifiedDeclarations(themeBlock(code));
      expect(kept.map(([name]) => name)).toEqual(
        declarations(themeBlock(source)).map(([name]) => name),
      );
      expect(kept.filter(([, value]) => value === "").map(([name]) => name)).toEqual([]);
    });

    it("writes no JSON: no brace, bracket or quoted key (quotes only in a font-family list)", () => {
      const json = declarations(bundle().source).filter(
        ([name, value]) =>
          /[{}[\]]/.test(value) ||
          /"[^"]*"\s*:/.test(value) ||
          (value.includes('"') && !name.endsWith("-font-family")),
      );
      expect(json).toEqual([]);
    });

    it("defines the custom properties each composite token of the sources needs", () => {
      const values = new Map(declarations(bundle().source));
      const { shadows, typography } = composites(themes[theme] ?? {});
      expect(shadows.length).toBeGreaterThan(0);
      expect(typography.length).toBeGreaterThan(0);
      // A shadow is one custom property, a box-shadow list; a typography token is one per field.
      for (const name of shadows) expect(values.get(name), name).toMatch(SHADOW);
      for (const part of typography.flatMap(({ parts }) => parts)) {
        expect(values.get(part), part).toBeTruthy();
        if (part.endsWith("-font-size")) expect(values.get(part), part).toMatch(/^[\d.]+px$/);
      }
      expect(typography.map(({ whole }) => whole).filter((name) => values.has(name))).toEqual([]);
    });
  });
});

// Each test builds a copy of the package, which a slow runner may take longer than the default 5 s for.
describe("token build CSS check (copied fixture tree)", { timeout: 30_000 }, () => {
  let sandbox: string | undefined;
  afterEach(() => {
    if (sandbox) rmSync(sandbox, { recursive: true, force: true });
    sandbox = undefined;
  });

  /** The output of a build whose semantic-dark set also carries `tokens`; it must fail. */
  function failingBuildWith(tokens: Record<string, Token>): string {
    sandbox = makeSandbox();
    const ui = path.join(sandbox, "packages", "ui");
    const file = path.join(ui, "tokens", "semantic-dark.tokens.json");
    const dark: Record<string, unknown> = JSON.parse(readFileSync(file, "utf-8"));
    writeFileSync(file, JSON.stringify({ ...dark, ...tokens }, null, 2));
    return failedBuildOutput(ui);
  }

  it("fails with TOKENS-E004 naming a custom property esbuild warns about", () => {
    const output = failingBuildWith({
      "space.test.unterminated": { $type: "spacing", $value: '"never closed' },
    });
    expect(output).toMatch(/TOKENS-E004.*tokens\.dark\.css/);
    expect(output).toMatch(/--space-test-unterminated \(line \d+\): Unterminated string/);
  });

  it("fails with TOKENS-E004 naming a custom property that is empty once minified", () => {
    const output = failingBuildWith({ "space.test.empty": { $type: "spacing", $value: "" } });
    expect(output).toMatch(/TOKENS-E004.*tokens\.dark\.css/);
    expect(output).toMatch(/--space-test-empty: empty once minified/);
  });

  it("fails with TOKENS-E004 naming a composite token the CSS writer has no form for", () => {
    const output = failingBuildWith({
      "type.test.cased": {
        $type: "typography",
        $value: { fontFamily: ["Inter"], fontSize: "12", textCase: "uppercase" },
      },
    });
    expect(output).toMatch(/TOKENS-E004 invalid CSS output: typography token "type\.test\.cased"/);
    expect(output).toMatch(/textCase/);
  });
});
