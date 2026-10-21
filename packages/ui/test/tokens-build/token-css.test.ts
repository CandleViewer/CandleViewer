// @vitest-environment node
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

type Token = { $type: string; $value: unknown };
// A plain `.mjs` script with no type declarations, loaded as label-on-fill.test.ts loads the build.
const tokenCss = (await import(/* @vite-ignore */ "../../scripts/token-css.mjs" as string)) as {
  cssValue(token: Token, name?: string): string;
  cssDeclarations(name: string, token: Token): [string, string][];
  cssProblems(css: string, file: string): Promise<string[]>;
  checkCss(css: string, file: string): Promise<void>;
};
const { cssValue, cssDeclarations, cssProblems, checkCss } = tokenCss;

const shadow = (value: unknown): Token => ({ $type: "shadow", $value: value });
const typography = (value: unknown): Token => ({ $type: "typography", $value: value });
const layer = { offsetX: "0", offsetY: "1", blur: "2", spread: "0", color: "#00000066" };
const label = { fontFamily: ["Inter"], fontSize: "12", fontWeight: "500", lineHeight: "1.2" };

describe("shadow tokens as a box-shadow value", () => {
  it("write one layer as `x y blur spread colour`, a bare number in px", () => {
    expect(cssValue(shadow(layer))).toBe("0px 1px 2px 0px #00000066");
  });

  it("join layers by a comma, put `inset` first and keep a unit as written", () => {
    const layers = [
      { offsetX: 0, offsetY: "2", blur: "4", spread: "-1", color: "#000000", inset: true },
      { offsetX: "0.5rem", offsetY: "1", blur: "2", spread: "0", color: "#FFF", inset: false },
    ];
    expect(cssValue(shadow(layers))).toBe(
      "inset 0px 2px 4px -1px #000000, 0.5rem 1px 2px 0px #FFF",
    );
  });

  it.each([
    ["has no blur", { ...layer, blur: undefined }, /"elevation\.x" has no blur/],
    ["has a field with no CSS form", { ...layer, type: "inner" }, /no CSS form: type/],
    ["has no layer", [], /"elevation\.x" has no layer/],
    ["has a length with no CSS form (`1.`)", { ...layer, offsetX: "1." }, /no CSS form: "1\."/],
    ["has a signed length (`+1`)", { ...layer, offsetY: "+1" }, /no CSS form: "\+1"/],
    ["has a null blur", { ...layer, blur: null }, /no CSS form: "null"/],
    [
      "has an inset that is not a boolean",
      { ...layer, inset: "True" },
      /inset that is not true or false/,
    ],
    ["has a numeric inset", { ...layer, inset: 1 }, /inset that is not true or false/],
  ])("fail with TOKENS-E004 for a shadow that %s", (_, value, message) => {
    expect(() => cssValue(shadow(value), "elevation.x")).toThrow(/^TOKENS-E004/);
    expect(() => cssValue(shadow(value), "elevation.x")).toThrow(message);
  });
});

describe("typography tokens as one custom property per field", () => {
  it("write each field the token has, in DTCG order, never the composite's own name", () => {
    expect(cssDeclarations("type.ui.label", typography(label))).toEqual([
      ["--type-ui-label-font-family", "Inter"],
      ["--type-ui-label-font-size", "12px"],
      ["--type-ui-label-font-weight", "500"],
      ["--type-ui-label-line-height", "1.2"],
    ]);
    const spaced = typography({ letterSpacing: "0.2", ...label });
    expect(cssDeclarations("type.x", spaced).map(([name]) => name)).toContain(
      "--type-x-letter-spacing",
    );
    expect(cssDeclarations("type.x", typography({ fontSize: 10 }))).toEqual([
      ["--type-x-font-size", "10px"],
    ]);
  });

  it.each([
    [["Inter"], "Inter"],
    [["JetBrains Mono", "ui-monospace", "monospace"], '"JetBrains Mono", ui-monospace, monospace'],
    [["Inter", "system-ui", "Segoe UI", "sans-serif"], 'Inter, system-ui, "Segoe UI", sans-serif'],
    ["1Password", '"1Password"'],
    [["inherit"], '"inherit"'],
    [['Say "Hi"'], '"Say \\"Hi\\""'],
  ])("write the font family %j as %s", (fontFamily, expected) => {
    expect(cssDeclarations("type.x", typography({ fontFamily }))[0]?.[1]).toBe(expected);
  });

  it.each([
    ["fontSize", "0.75rem", "0.75rem"],
    ["letterSpacing", "0.2", "0.2px"],
    ["letterSpacing", "0", "0px"],
    ["letterSpacing", "0.01em", "0.01em"],
    ["fontWeight", 600, "600"],
    ["lineHeight", 1.5, "1.5"],
    ["lineHeight", "20px", "20px"],
  ])("write %s %j as %s", (field, value, expected) => {
    expect(cssDeclarations("type.x", typography({ [field]: value }))[0]?.[1]).toBe(expected);
  });

  it.each([
    ["a field with no CSS part", { ...label, textCase: "upper" }, /with no CSS part: textCase/],
    ["no field", {}, /"type\.x" has no field/],
    ["a value that is not an object", "{type.ui.label}", /is not an object of fields/],
  ])("fail with TOKENS-E004 for a typography token with %s", (_, value, message) => {
    expect(() => cssDeclarations("type.x", typography(value))).toThrow(/^TOKENS-E004/);
    expect(() => cssDeclarations("type.x", typography(value))).toThrow(message);
  });
});

describe("other tokens", () => {
  it("keep their form: px for a bare spacing, lists joined, anything else as written", () => {
    expect(cssDeclarations("space.gap", { $type: "spacing", $value: "8" })).toEqual([
      ["--space-gap", "8px"],
    ]);
    expect(cssValue({ $type: "cubicBezier", $value: [0.2, 0, 0, 1] })).toBe("0.2, 0, 0, 1");
    expect(cssValue({ $type: "fontSizes", $value: "11" })).toBe("11");
    expect(cssValue({ $type: "color", $value: "#2EBD59" })).toBe("#2EBD59");
  });

  it("fail with TOKENS-E004 for an object of a type that has no CSS form, naming the token", () => {
    const border: Token = {
      $type: "border",
      $value: { color: "#FFF", width: "1", style: "solid" },
    };
    expect(() => cssDeclarations("border.card", border)).toThrow(/^TOKENS-E004.*"border\.card"/);
  });
});

describe("a value that would end or escape its declaration (the minifier accepts it)", () => {
  const color = (value: string): Token => ({ $type: "color", $value: value });

  it.each([
    ["appends a declaration", "#fff; --evil: 1"],
    ["closes the theme block and opens a rule", "#fff } .evil { color: red"],
    ["breaks the line", "#fff\n  --evil: 1"],
    ["opens a comment", "#fff /* --evil: 1 */"],
  ])("fails with TOKENS-E004 when a colour %s", (_, value) => {
    expect(() => cssValue(color(value), "color.x")).toThrow(
      /^TOKENS-E004 invalid CSS output: token "color\.x" has a value that would end or escape/,
    );
  });

  it("fails the same way through a shadow colour, a typography part and a token name", () => {
    expect(() => cssValue(shadow({ ...layer, color: "#000; --x: 1" }), "elevation.x")).toThrow(
      /"elevation\.x" has a value that would end or escape/,
    );
    expect(() => cssDeclarations("type.x", typography({ ...label, fontWeight: "500}" }))).toThrow(
      /"type\.x" has a value that would end or escape/,
    );
    expect(() => cssDeclarations("color.x}", color("#fff"))).toThrow(
      /"color\.x}" has a name that would end or escape/,
    );
  });

  it("fails closed on a quoted family name that holds one, though the quotes would contain it", () => {
    expect(() => cssDeclarations("type.x", typography({ fontFamily: ["a; b"] }))).toThrow(
      /^TOKENS-E004/,
    );
  });
});

describe("the check's esbuild", () => {
  it("is the version Vite minifies the production CSS with, so it reads CSS as the bundle does", () => {
    const here = path.dirname(fileURLToPath(import.meta.url));
    const ui = createRequire(path.resolve(here, "../../package.json"));
    const web = createRequire(path.resolve(here, "../../../../apps/web/package.json"));
    const vite = createRequire(web.resolve("vite/package.json"));
    const version = (from: NodeRequire): string =>
      (from("esbuild/package.json") as { version: string }).version;
    expect(version(ui)).toBe(version(vite));
  });
});

describe("the CSS check, as the production minifier (esbuild) reads CSS", () => {
  const file = "build/css/tokens.dark.css";
  const block = (...lines: string[]) => `[data-theme="dark"] {\n${lines.join("\n")}\n}\n`;

  it("finds no problem in what the build writes for composite tokens", async () => {
    const css = block(
      "  --elevation-1: 0px 1px 2px 0px #00000066;",
      '  --type-num-base-font-family: "JetBrains Mono";',
      "  --type-ui-label-font-size: 12px;",
    );
    expect(await cssProblems(css, file)).toEqual([]);
    await expect(checkCss(css, file)).resolves.toBeUndefined();
  });

  it("names each custom property whose JSON value esbuild warns about, with its line", async () => {
    const css = block(
      "  --a: 1px;",
      '  --elevation-0: {"offsetX":"0","blur":"0"};',
      '  --type-ui-label: {"fontFamily":["Inter"]};',
    );
    const problems = await cssProblems(css, file);
    expect(problems.map((problem) => problem.slice(0, problem.indexOf(":")))).toEqual([
      "--elevation-0 (line 3)",
      "--elevation-0 (line 3)",
      "--type-ui-label (line 4)",
      "--type-ui-label (line 4)",
    ]);
    await expect(checkCss(css, file)).rejects.toThrow(
      /^TOKENS-E004 invalid CSS output: build\/css\/tokens\.dark\.css does not minify cleanly \(4\):\n/,
    );
  });

  it.each(["--a: ;", "--a:;"])("names a custom property empty once minified (`%s`)", async (d) => {
    expect(await cssProblems(block(d, "  --b: 1;"), file)).toEqual(["--a: empty once minified"]);
  });

  it("names the file when a problem is not on a declaration line", async () => {
    expect(await cssProblems('[data-theme="dark"] {\n  --a: 1px;\n', file)).toEqual([
      `${file} (line 3): Expected "}" to go with "{"`,
    ]);
  });
});
