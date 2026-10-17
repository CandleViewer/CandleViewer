#!/usr/bin/env node
// Copies the CSS that apps import into `dist/`, next to the JS entry, so the package `exports` point at
// built files (`./theme.css`, `./tokens.*.css`) and never at `src/` (the deep-import ban, CONSTITUTION §9 #18).
//
// Run by tsup's `onSuccess` after every build (`pnpm --filter @candleviewer/ui build`), which first runs
// `build:tokens`, so the generated `build/css/tokens.*.css` exist. `--no-tokens` copies `theme.css` only
// (the unit test uses it: the token integration test deletes and rebuilds `build/` concurrently).
import { copyFile, mkdir, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const UI_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/** Copies the CSS into `<root>/dist` and returns the file names written. */
export async function copyCss(root = UI_ROOT, { tokens = true } = {}) {
  const dist = path.join(root, "dist");
  await mkdir(dist, { recursive: true });
  const sources = [path.join(root, "src/theme/theme.css")];
  if (tokens) {
    const dir = path.join(root, "build/css");
    const names = await readdir(dir).catch(() => []);
    sources.push(...names.filter((n) => /^tokens\..+\.css$/.test(n)).map((n) => path.join(dir, n)));
  }
  for (const source of sources) await copyFile(source, path.join(dist, path.basename(source)));
  return sources.map((source) => path.basename(source));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const written = await copyCss(UI_ROOT, { tokens: !process.argv.includes("--no-tokens") });
  console.log(`[copy-css] dist/: ${written.join(", ")}`);
}
