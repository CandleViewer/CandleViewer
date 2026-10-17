import { execFileSync } from "node:child_process";
import {
  mkdtempSync,
  rmSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  existsSync,
  cpSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const UI_ROOT = path.resolve(__dirname, "..", "..");
const BUILD_SCRIPT = path.join(UI_ROOT, "scripts", "build-tokens.mjs");

function runBuild(cwd = UI_ROOT) {
  const script = path.join(cwd, "scripts", "build-tokens.mjs");
  return execFileSync(process.execPath, [script], { cwd, encoding: "utf-8" });
}

/** A temp copy of the files the token build reads; `<dir>/packages/ui` is where it builds. */
function makeSandbox() {
  const dir = mkdtempSync(path.join(tmpdir(), "cv-tokens-"));
  mkdirSync(path.join(dir, "packages", "ui", "tokens"), { recursive: true });
  cpSync(path.join(UI_ROOT, "tokens"), path.join(dir, "packages", "ui", "tokens"), {
    recursive: true,
  });
  mkdirSync(path.join(dir, "packages", "ui", "scripts"), { recursive: true });
  cpSync(BUILD_SCRIPT, path.join(dir, "packages", "ui", "scripts", "build-tokens.mjs"));
  cpSync(
    path.join(UI_ROOT, "scripts", "chart-color-modes.mjs"),
    path.join(dir, "packages", "ui", "scripts", "chart-color-modes.mjs"),
  );
  mkdirSync(path.join(dir, "tools", "style-dictionary", "formats"), { recursive: true });
  cpSync(
    path.join(UI_ROOT, "..", "..", "tools", "style-dictionary", "formats"),
    path.join(dir, "tools", "style-dictionary", "formats"),
    { recursive: true },
  );
  cpSync(
    path.join(UI_ROOT, "..", "..", "tools", "style-dictionary", "package.json"),
    path.join(dir, "tools", "style-dictionary", "package.json"),
  );
  return dir;
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

  it("produces all six documented, non-empty artefacts", () => {
    runBuild(ui);
    const artefacts = [
      "css/tokens.dark.css",
      "css/tokens.light.css",
      "css/tokens.high-contrast.css",
      "ts/tokens.ts",
      "engine/theme-uniforms.json",
      "electron/tokens.main.json",
    ];
    for (const rel of artefacts) {
      const full = path.join(buildDir, rel);
      expect(existsSync(full), `missing artefact: ${rel}`).toBe(true);
      expect(readFileSync(full, "utf-8").length).toBeGreaterThan(0);
    }
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
