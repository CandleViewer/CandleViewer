#!/usr/bin/env node
// Copies the CSS that apps import into `dist/`, next to the JS entry, so the package `exports` point at
// built files (`./theme.css`, `./components.css`, `./tokens.*.css`) and never at `src/` (the deep-import ban, CONSTITUTION §9 #18).
//
// Run by tsup's `onSuccess` after every build (`pnpm --filter @candleviewer/ui build`), which first runs
// `build:tokens`, so the generated `build/css/tokens.*.css` exist. It throws when one of them is missing
// and copies nothing, so a build cannot ship `dist/` without the token CSS. `--no-tokens` copies
// `theme.css` only (a bare `test` run has no `build/` yet).
//
// A plain script with no entry-point guard: it always runs, so it cannot turn into a silent no-op (exit 0,
// nothing copied) when it is started through a symlink or junction path.
import { copyFile, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const UI_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
/** `build:tokens` writes one token CSS file per theme; all three must exist. */
const TOKEN_FILES = ["dark", "light", "high-contrast"].map((theme) => `tokens.${theme}.css`);

const sources = [path.join(UI_ROOT, "src/theme/theme.css")];
if (!process.argv.includes("--no-tokens")) {
  const dir = path.join(UI_ROOT, "build/css");
  const names = await readdir(dir).catch(() => []);
  const missing = TOKEN_FILES.filter((name) => !names.includes(name));
  if (missing.length > 0) {
    throw new Error(`copy-css: ${dir} lacks ${missing.join(", ")}; run build:tokens first`);
  }
  sources.push(...names.filter((n) => /^tokens\..+\.css$/.test(n)).map((n) => path.join(dir, n)));
}
const dist = path.join(UI_ROOT, "dist");
await mkdir(dist, { recursive: true });
for (const source of sources) await copyFile(source, path.join(dist, path.basename(source)));
// Component CSS (`src/components/*.css`) ships as one `components.css`: the shared `controls.css` first, then
// each component's file in name order, so the foundation never depends on import order.
const componentDir = path.join(UI_ROOT, "src/components");
const componentFiles = (await readdir(componentDir).catch(() => []))
  .filter((name) => name.endsWith(".css"))
  .sort((a, b) => (a === "controls.css" ? -1 : b === "controls.css" ? 1 : a.localeCompare(b)));
const written = sources.map((source) => path.basename(source));
if (componentFiles.length > 0) {
  const parts = await Promise.all(componentFiles.map((n) => readFile(path.join(componentDir, n))));
  await writeFile(path.join(dist, "components.css"), parts.join("\n"));
  written.push("components.css");
}
console.log(`[copy-css] dist/: ${written.join(", ")}`);
