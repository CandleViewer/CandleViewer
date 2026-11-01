import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import ts from "typescript";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { tokenRows } from "../../src/docs/TokenTables.js";
import { UI_ROOT, makeSandbox, runBuild } from "./sandbox.js";

/**
 * The `tokens` tree a generated `build/ts/tokens.ts` exports, as the Foundations page imports it.
 * The sandbox lies outside the folders Vite may load from, so the module is transpiled and Node
 * imports it natively, as a data: URL.
 */
async function generatedTokens(file: string): Promise<object> {
  const { outputText } = ts.transpileModule(readFileSync(file, "utf-8"), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  });
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`;
  const { tokens } = (await import(/* @vite-ignore */ url)) as { tokens: object };
  return tokens;
}

// The real `build/` feeds `dist/` (tsup's `onSuccess`) and other lanes, and `ui#build` may run beside the
// tests, so nothing here builds into or deletes it: the builds run in a temp copy.
describe("token build integration (real Style Dictionary run)", () => {
  let sandbox = "";
  let ui = "";
  let buildDir = "";
  beforeAll(() => {
    sandbox = makeSandbox();
    ui = path.join(sandbox, "packages", "ui");
    buildDir = path.join(ui, "build");
  });
  afterAll(() => {
    rmSync(sandbox, { recursive: true, force: true });
  });

  it("produces all nine documented, non-empty artefacts", () => {
    runBuild(ui);
    const artefacts = [
      "css/tokens.dark.css",
      "css/tokens.light.css",
      "css/tokens.high-contrast.css",
      "ts/tokens.ts",
      "engine/theme-uniforms.json",
      "engine/theme-uniforms.dark.json",
      "engine/theme-uniforms.light.json",
      "engine/theme-uniforms.high-contrast.json",
      "electron/tokens.main.json",
    ];
    for (const rel of artefacts) {
      const full = path.join(buildDir, rel);
      expect(existsSync(full), `missing artefact: ${rel}`).toBe(true);
      expect(readFileSync(full, "utf-8").length).toBeGreaterThan(0);
    }
  });

  it("emits every theme bundle the Storybook preview imports, each under its data-theme", () => {
    runBuild(ui);
    const preview = readFileSync(path.join(UI_ROOT, ".storybook", "theme-bundles.ts"), "utf-8");
    const bundles = [
      ...preview.matchAll(/^import "\.\.\/build\/(css\/tokens\.([\w-]+)\.css)";$/gm),
    ];
    expect(bundles.map((match) => match[2])).toEqual(["dark", "light", "high-contrast"]);
    for (const [, rel = "", theme] of bundles) {
      const css = readFileSync(path.join(buildDir, rel), "utf-8");
      expect(css).toContain(`[data-theme="${theme}"] {`);
    }
  });

  it("gives the Foundations page a row for every theme bundle property but --size-icon", async () => {
    runBuild(ui);
    // The page renders tokenRows(tokens) from build/ts/tokens.ts, and says it cannot drift from it.
    const tokens = await generatedTokens(path.join(buildDir, "ts", "tokens.ts"));
    const rows = new Set(tokenRows(tokens).map(({ property }) => property));
    const declared = (theme: string) => {
      const css = readFileSync(path.join(buildDir, "css", `tokens.${theme}.css`), "utf-8");
      return new Set([...css.matchAll(/^\s*(--[\w-]+):/gm)].map(([, name = ""]) => name));
    };
    const dark = declared("dark");
    // Only --size-icon, a CSS leaf beside size.icon.*, has no place in the nested tree.
    expect([...dark].filter((name) => !rows.has(name))).toEqual(["--size-icon"]);
    expect([...rows].filter((name) => !dark.has(name))).toEqual([]);
    // The light and high-contrast bundles define the same properties, as the page says.
    expect([declared("light"), declared("high-contrast")]).toEqual([dark, dark]);
  });

  it("is byte-identical across two consecutive runs (deterministic build)", () => {
    runBuild(ui);
    const snapshot: Record<string, string> = {};
    for (const rel of [
      "css/tokens.dark.css",
      "ts/tokens.ts",
      "engine/theme-uniforms.json",
      "electron/tokens.main.json",
    ]) {
      snapshot[rel] = readFileSync(path.join(buildDir, rel), "utf-8");
    }
    rmSync(buildDir, { recursive: true, force: true });
    runBuild(ui);
    for (const rel of Object.keys(snapshot)) {
      expect(readFileSync(path.join(buildDir, rel), "utf-8")).toBe(snapshot[rel]);
    }
  });

  it("emits every chart-category token as numeric RGBA with no hex-string leakage in values", () => {
    runBuild(ui);
    const uniforms = JSON.parse(
      readFileSync(path.join(buildDir, "engine", "theme-uniforms.json"), "utf-8"),
    );
    expect(Object.keys(uniforms).length).toBeGreaterThan(0);
    for (const [name, entry] of Object.entries(uniforms) as [
      string,
      { rgba: number[]; hex: string },
    ][]) {
      expect(Array.isArray(entry.rgba), `${name} rgba is an array`).toBe(true);
      expect(entry.rgba).toHaveLength(4);
      for (const channel of entry.rgba) {
        expect(channel).toBeGreaterThanOrEqual(0);
        expect(channel).toBeLessThanOrEqual(1);
      }
      expect(entry.hex).toMatch(/^#[0-9A-F]{6,8}$/);
    }
  });

  it("emits one engine export per theme, and the dark one under the original name too", () => {
    runBuild(ui);
    const read = (file: string) => readFileSync(path.join(buildDir, "engine", file), "utf-8");
    const dark = read("theme-uniforms.dark.json");
    expect(read("theme-uniforms.json")).toBe(dark);
    const names = (json: string) => Object.keys(JSON.parse(json) as object);
    // Theme parity: every export carries exactly the same names.
    for (const theme of ["light", "high-contrast"]) {
      expect(names(read(`theme-uniforms.${theme}.json`))).toEqual(names(dark));
    }
  });

  it("resolves every chart slot and engine-chrome alias per theme (E11-D05 §4.1, §4.1b)", () => {
    runBuild(ui);
    const hex = (theme: string) => {
      const file = path.join(buildDir, "engine", `theme-uniforms.${theme}.json`);
      const map = JSON.parse(readFileSync(file, "utf-8")) as Record<string, { hex: string }>;
      return (name: string) => map[name]?.hex;
    };
    // [slot, dark, light, high-contrast]: the resolved values E11-D05 §4.1 / §4.1b record.
    const slots: [string, string, string, string][] = [
      ["color.chart.axis", "#8B949E", "#525C66", "#C9D1D9"],
      ["color.chart.grid.major", "#2E363E", "#D6DAE0", "#586470"],
      ["color.chart.grid.minor", "#1C222B", "#E3E6EA", "#11151A"],
      ["color.chart.crosshair", "#B1BAC4", "#3A4148", "#B1BAC4"],
      ["color.chart.watermark", "#2E363E", "#D6DAE0", "#586470"],
      ["color.chart.pane.bg.default", "#11151A", "#F6F7F9", "#11151A"],
      ["color.chart.pane.bg.focused", "#11151A", "#F6F7F9", "#11151A"],
      ["color.chart.replay.border", "#A78BFA", "#7040E0", "#A78BFA"],
      ["color.chart.boundary", "#8B949E", "#525C66", "#C9D1D9"],
      ["color.chart.rule", "#2E363E", "#D6DAE0", "#586470"],
      ["color.chart.hatch.texture", "#3D4650", "#C2C8D0", "#3D4650"],
      ["color.chart.pill.bg", "#161B22", "#EDEFF2", "#161B22"],
      ["color.chart.pill.border", "#3D4650", "#C2C8D0", "#3D4650"],
      ["color.chart.pill.text.default", "#E8EAED", "#14171A", "#F6F8FA"],
      ["color.chart.pill.text.inverse", "#0B0E11", "#FFFFFF", "#0B0E11"],
      ["color.chart.pill.text.on-marker", "#FFFFFF", "#FFFFFF", "#0B0E11"],
      ["color.chart.marker.goto", "#2B6CE8", "#2B6CE8", "#6EA1F5"],
      ["color.chart.focus.ring", "#6EA1F5", "#1F55BF", "#FFFFFF"],
    ];
    const [dark, light, hc] = [hex("dark"), hex("light"), hex("high-contrast")];
    for (const [slot, d, l, h] of slots) {
      expect([dark(slot), light(slot), hc(slot)], slot).toEqual([d, l, h]);
    }
    // G16: the CVD-safe heatmap stops ride in the export.
    expect(dark("color.cvd.heatmap.bid.1")).toMatch(/^#[0-9A-F]{6}$/);
  });

  it("emits a flat, CSS/TS-free JSON map for the Electron main process", () => {
    runBuild(ui);
    const flat = JSON.parse(
      readFileSync(path.join(buildDir, "electron", "tokens.main.json"), "utf-8"),
    );
    expect(flat["color.buy.default"]).toBe("#2EBD59");
    for (const value of Object.values(flat)) {
      if (typeof value === "string") {
        expect(value).not.toMatch(/var\(--/);
      }
    }
  });
});

describe("token build failure modes (copied fixture tree)", () => {
  let sandbox: string | undefined;

  afterEach(() => {
    if (sandbox) rmSync(sandbox, { recursive: true, force: true });
    sandbox = undefined;
  });

  it("fails with TOKENS-E001 when a theme defines a token the others don't", () => {
    sandbox = makeSandbox();
    const lightPath = path.join(sandbox, "packages", "ui", "tokens", "semantic-light.tokens.json");
    const light = JSON.parse(readFileSync(lightPath, "utf-8"));
    light["color.light-only.experimental"] = { $type: "color", $value: "#123456" };
    writeFileSync(lightPath, JSON.stringify(light, null, 2));

    expect(() => runBuild(path.join(sandbox as string, "packages", "ui"))).toThrowError();
    try {
      runBuild(path.join(sandbox as string, "packages", "ui"));
    } catch (err) {
      const e = err as { stdout?: string; stderr?: string };
      const output = String(e.stdout ?? "") + String(e.stderr ?? "");
      expect(output).toMatch(/TOKENS-E001/);
      expect(output).toMatch(/color\.light-only\.experimental/);
    }
  });

  it("fails with TOKENS-E002 when a token references a dangling alias", () => {
    sandbox = makeSandbox();
    const darkPath = path.join(sandbox, "packages", "ui", "tokens", "semantic-dark.tokens.json");
    const dark = JSON.parse(readFileSync(darkPath, "utf-8"));
    dark["color.buy.default"] = { $type: "color", $value: "{palette.does-not-exist}" };
    writeFileSync(darkPath, JSON.stringify(dark, null, 2));

    try {
      runBuild(path.join(sandbox, "packages", "ui"));
      expect.fail("expected build to throw");
    } catch (err) {
      const e = err as { stdout?: string; stderr?: string };
      const output = String(e.stdout ?? "") + String(e.stderr ?? "");
      expect(output).toMatch(/TOKENS-E002/);
    }
  });
});
