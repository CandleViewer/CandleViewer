#!/usr/bin/env node
// #3244: fail fast when a workspace package's built exports are missing. apps/web's tests can
// import built artefacts of the packages it depends on (turbo builds them first through `^build`),
// so a lane that runs those tests with pnpm directly must build them first; this guard makes a
// missing build fail with a clear message instead of a confusing test failure.
//
// Every export target must be a file. A pattern target (`./dist/tokens.*.css`) must match at least
// one file, so a pattern export is never skipped.
//
// Usage: node tools/ci/check_built_exports.mjs <package-dir> [<package-dir> ...]
import { readdirSync, readFileSync, statSync } from "node:fs";
import { basename, dirname, join } from "node:path";

const CODE = "CI-BUILD-001";

function targets(node, out) {
  if (typeof node === "string") out.push(node);
  else if (node && typeof node === "object")
    for (const value of Object.values(node)) targets(value, out);
  return out;
}

function isFile(path) {
  return statSync(path, { throwIfNoEntry: false })?.isFile() ?? false;
}

function present(dir, target) {
  if (!target.includes("*")) return isFile(join(dir, target));
  const folder = join(dir, dirname(target));
  const escaped = basename(target)
    .replace(/[.+?^${}()|[\]\\]/g, "\\$&")
    .replaceAll("*", ".+");
  const pattern = new RegExp(`^${escaped}$`);
  const names = statSync(folder, { throwIfNoEntry: false })?.isDirectory()
    ? readdirSync(folder)
    : [];
  return names.some((name) => pattern.test(name) && isFile(join(folder, name)));
}

function exportsOf(dir) {
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
  } catch (err) {
    console.error(`${CODE}: cannot read ${join(dir, "package.json")}: ${err.message}`);
    process.exit(1);
  }
  const files = targets(manifest.exports ?? manifest.main ?? [], []);
  if (files.length === 0) {
    console.error(`${CODE}: ${dir}/package.json declares no exports to check`);
    process.exit(1);
  }
  return files;
}

function main(dirs) {
  if (dirs.length === 0) {
    console.error("usage: node tools/ci/check_built_exports.mjs <package-dir> [<package-dir> ...]");
    process.exit(2);
  }
  const missing = [];
  for (const dir of dirs) {
    for (const target of exportsOf(dir)) {
      if (!present(dir, target)) missing.push(join(dir, target));
    }
  }
  if (missing.length > 0) {
    console.error(
      `${CODE}: built exports are missing; build the workspace packages first ` +
        '(pnpm --filter "@candleviewer/web^..." run build):',
    );
    for (const file of missing) console.error(`  ${file}`);
    process.exit(1);
  }
  console.log(`check_built_exports: OK (${dirs.join(", ")})`);
}

main(process.argv.slice(2));
