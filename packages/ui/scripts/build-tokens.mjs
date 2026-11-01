#!/usr/bin/env node
// The single Style Dictionary build entry point for @candleviewer/ui.
//
// Run via `pnpm --filter @candleviewer/ui build:tokens`. Produces the
// artefacts from docs/plan/16-design-system-brief.md §11:
//   build/css/tokens.{dark,light,high-contrast}.css
//   build/ts/tokens.ts
//   build/engine/theme-uniforms.{dark,light,high-contrast}.json (one per theme, §11.1)
//   build/engine/theme-uniforms.json (the dark export under its original name)
//   build/electron/tokens.main.json
//
// Determinism (ticket AC "second run produces byte-identical output"):
// no timestamps in output headers, all token/object keys sorted before
// serialisation, Style Dictionary pinned in the lockfile.
//
// Error codes (docs/plan/16-design-system-brief.md / ticket technical notes):
//   TOKENS-E001 missing-theme-parity — a token present in one theme, absent in another.
//   TOKENS-E002 unresolved alias reference — a `{token.path}` that never resolves.
//   TOKENS-E003 unknown category for the engine filter — a chart-category token
//               resolved to something other than a hex colour string.
//   TOKENS-E004 invalid CSS output — a token the CSS writer cannot serialise or would let
//               the browser misread (token-css.mjs), or a theme's CSS that esbuild warns
//               about or minifies to an empty custom property, checked before it is written.
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import jsonFlatRgba from "../../../tools/style-dictionary/formats/json-flat-rgba.js";
import jsonFlat from "../../../tools/style-dictionary/formats/json-flat.js";
import { modeCss } from "./chart-color-modes.mjs";
import { checkCss, cssDeclarations, cssValue } from "./token-css.mjs";
import typescriptNestedObject from "../../../tools/style-dictionary/formats/typescript-nested.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const UI_ROOT = path.resolve(__dirname, "..");
const TOKENS_DIR = path.join(UI_ROOT, "tokens");
const BUILD_DIR = path.join(UI_ROOT, "build");

async function loadJson(file) {
  return JSON.parse(await readFile(path.join(TOKENS_DIR, file), "utf-8"));
}

/** Later sets override earlier ones (theme composition order in themes.json). */
function mergeSets(sets) {
  const merged = {};
  for (const set of sets) Object.assign(merged, set);
  return merged;
}

/** Resolve every `{token.path}` reference in `value` against `allTokens`. */
function resolve(value, allTokens, tokenName, seen = new Set()) {
  if (typeof value === "string" && value.startsWith("{") && value.endsWith("}")) {
    const ref = value.slice(1, -1);
    if (seen.has(ref)) {
      throw new Error(
        `TOKENS-E002 unresolved alias reference: circular reference "${ref}" from token "${tokenName}"`,
      );
    }
    if (!(ref in allTokens)) {
      throw new Error(
        `TOKENS-E002 unresolved alias reference: token "${tokenName}" references unknown "${ref}"`,
      );
    }
    return resolve(allTokens[ref].$value, allTokens, tokenName, new Set(seen).add(ref));
  }
  if (Array.isArray(value)) return value.map((v) => resolve(v, allTokens, tokenName, seen));
  if (value && typeof value === "object") {
    const out = {};
    for (const k of Object.keys(value)) out[k] = resolve(value[k], allTokens, tokenName, seen);
    return out;
  }
  return value;
}

/** Fully resolve every token in a merged theme set; throws TOKENS-E002 on a dangling ref. */
function resolveTheme(merged) {
  const resolved = {};
  for (const name of Object.keys(merged)) {
    resolved[name] = { ...merged[name], $value: resolve(merged[name].$value, merged, name) };
  }
  return resolved;
}

/**
 * Loads and fully resolves all 3 themes from `tokens/*.tokens.json`
 * (the design-token source of truth — never the Figma file). Exported so
 * `tools/contrast/generate.mjs` (E05-T05) can consume the same resolved
 * colour values the build itself produces, rather than re-parsing generated
 * CSS/JSON output.
 * @returns {Promise<Record<string, Record<string, unknown>>>}
 */
export async function loadResolvedThemes() {
  const primitives = await loadJson("primitives.tokens.json");

  const themeFiles = {
    dark: ["semantic-dark.tokens.json"],
    light: ["semantic-dark.tokens.json", "semantic-light.tokens.json"],
    "high-contrast": ["semantic-dark.tokens.json", "semantic-hc.tokens.json"],
  };

  /** @type {Record<string, Record<string, unknown>>} */
  const resolvedThemes = {};
  for (const [themeName, files] of Object.entries(themeFiles)) {
    const sets = [primitives, ...(await Promise.all(files.map((f) => loadJson(f))))];
    resolvedThemes[themeName] = resolveTheme(mergeSets(sets));
  }
  return resolvedThemes;
}

async function main() {
  const resolvedThemes = await loadResolvedThemes();

  checkThemeParity(resolvedThemes);

  await mkdir(path.join(BUILD_DIR, "css"), { recursive: true });
  await mkdir(path.join(BUILD_DIR, "ts"), { recursive: true });
  await mkdir(path.join(BUILD_DIR, "engine"), { recursive: true });
  await mkdir(path.join(BUILD_DIR, "electron"), { recursive: true });

  await buildCss("dark", resolvedThemes.dark);
  await buildCss("light", resolvedThemes.light);
  await buildCss("high-contrast", resolvedThemes["high-contrast"]);

  await buildTs(resolvedThemes.dark);
  for (const themeName of ENGINE_THEMES) await buildEngine(themeName, resolvedThemes[themeName]);
  await buildElectron(resolvedThemes.dark);

  logSummary(resolvedThemes);
}

/** TOKENS-E001: every theme must define exactly the same token names. */
function checkThemeParity(resolvedThemes) {
  const names = Object.keys(resolvedThemes);
  const keySets = names.map((n) => new Set(Object.keys(resolvedThemes[n])));
  const [first, ...rest] = keySets;
  for (let i = 0; i < rest.length; i++) {
    const other = rest[i];
    const missingInOther = [...first].filter((k) => !other.has(k));
    const missingInFirst = [...other].filter((k) => !first.has(k));
    const missing = [...missingInOther, ...missingInFirst];
    if (missing.length > 0) {
      throw new Error(
        `TOKENS-E001 missing-theme-parity: theme "${names[0]}" vs "${names[i + 1]}" disagree on token(s): ${missing.sort().join(", ")}`,
      );
    }
  }
}

/**
 * Writes `build/css/tokens.<theme>.css`: one `[data-theme="<theme>"]` block
 * of `--category-subcategory-...: value;` custom properties, one per
 * resolved token (a typography token: one per field), name-sorted for
 * determinism (ticket AC: byte-identical on a second run). Each file is
 * checked before it is written (TOKENS-E004, token-css.mjs).
 */
async function buildCss(themeName, resolved) {
  const header =
    "/**\n * Do not edit directly — generated by `pnpm --filter @candleviewer/ui build:tokens`.\n */\n\n";
  const names = Object.keys(resolved).sort();
  const lines = names.flatMap((name) =>
    cssDeclarations(name, resolved[name]).map(([property, value]) => `  ${property}: ${value};`),
  );
  const content = `${header}[data-theme="${themeName}"] {\n${lines.join("\n")}\n}\n\n${modeCss(themeName, resolved, cssValue)}`;
  const file = path.join(BUILD_DIR, "css", `tokens.${themeName}.css`);
  // Checked before it is written: a file that fails TOKENS-E004 never reaches build/css or dist.
  await checkCss(content, path.relative(UI_ROOT, file).split(path.sep).join("/"));
  await writeFile(file, content, "utf-8");
}

async function buildTs(resolvedDark) {
  const allTokens = Object.entries(resolvedDark).map(([name, t]) => ({ name, value: t.$value }));
  const content = typescriptNestedObject({ dictionary: { allTokens } });
  await writeFile(path.join(BUILD_DIR, "ts", "tokens.ts"), content, "utf-8");
}

/** The themes that get an engine export, each loaded by the host for the active theme (§11.1). */
export const ENGINE_THEMES = ["dark", "light", "high-contrast"];

/**
 * Writes `build/engine/theme-uniforms.<theme>.json`. The dark export is also written to
 * `theme-uniforms.json`, the name the engine contract had before the per-theme files, so a
 * consumer of that name keeps reading the same bytes.
 */
async function buildEngine(themeName, resolved) {
  const allTokens = Object.entries(resolved).map(([name, t]) => ({ name, value: t.$value }));
  const content = jsonFlatRgba({ dictionary: { allTokens } });
  const dir = path.join(BUILD_DIR, "engine");
  await writeFile(path.join(dir, `theme-uniforms.${themeName}.json`), content, "utf-8");
  if (themeName === "dark")
    await writeFile(path.join(dir, "theme-uniforms.json"), content, "utf-8");
}

async function buildElectron(resolvedDark) {
  const allTokens = Object.entries(resolvedDark).map(([name, t]) => ({ name, value: t.$value }));
  const content = jsonFlat({ dictionary: { allTokens } });
  await writeFile(path.join(BUILD_DIR, "electron", "tokens.main.json"), content, "utf-8");
}

function logSummary(resolvedThemes) {
  for (const [theme, tokens] of Object.entries(resolvedThemes)) {
    const perCategory = {};
    for (const name of Object.keys(tokens)) {
      const cat = name.split(".")[0];
      perCategory[cat] = (perCategory[cat] ?? 0) + 1;
    }
    console.log(
      `[tokens:build] theme=${theme} total=${Object.keys(tokens).length} ${JSON.stringify(perCategory)}`,
    );
  }
}

// Only run the build (and its process.exit-on-failure behaviour) when this
// file is executed directly (`node scripts/build-tokens.mjs`), not when
// `loadResolvedThemes` is imported by another module (E05-T05's contrast
// gate).
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((err) => {
    console.error(err.stack ?? err.message ?? err);
    process.exitCode = 1;
  });
}
