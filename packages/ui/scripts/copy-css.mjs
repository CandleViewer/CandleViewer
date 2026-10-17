#!/usr/bin/env node
// Copies the CSS that apps import into `dist/`, next to the JS entry, so the package `exports` point at
// built files (`./theme.css`, `./tokens.*.css`) and never at `src/` (the deep-import ban, CONSTITUTION §9 #18).
//
// Run by tsup's `onSuccess` after every build (`pnpm --filter @candleviewer/ui build`), which first runs
// `build:tokens`, so the generated `build/css/tokens.*.css` exist. It throws when one of them is missing
// and copies nothing, so a build cannot ship `dist/` without the token CSS. `--no-tokens` copies
// `theme.css` only (a bare `test` run has no `build/` yet).
import { copyFile, mkdir, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const UI_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
/** `build:tokens` writes one token CSS file per theme; all three must exist. */
const TOKEN_FILES = ["dark", "light", "high-contrast"].map((theme) => `tokens.${theme}.css`);

/** Copies the CSS into `<root>/dist` and returns the file names written. */
export async function copyCss(root = UI_ROOT, { tokens = true } = {}) {
  const sources = [path.join(root, "src/theme/theme.css")];
  if (tokens) {
    const dir = path.join(root, "build/css");
    const names = await readdir(dir).catch(() => []);
    const missing = TOKEN_FILES.filter((name) => !names.includes(name));
    if (missing.length > 0) {
      throw new Error(`copy-css: ${dir} lacks ${missing.join(", ")}; run build:tokens first`);
    }
    sources.push(...names.filter((n) => /^tokens\..+\.css$/.test(n)).map((n) => path.join(dir, n)));
  }
  const dist = path.join(root, "dist");
  await mkdir(dist, { recursive: true });
  for (const source of sources) await copyFile(source, path.join(dist, path.basename(source)));
  return sources.map((source) => path.basename(source));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const written = await copyCss(UI_ROOT, { tokens: !process.argv.includes("--no-tokens") });
  console.log(`[copy-css] dist/: ${written.join(", ")}`);
}
