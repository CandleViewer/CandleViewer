#!/usr/bin/env node
// #3244: fail fast when a workspace package's built exports are missing. apps/web's tests can
// import built artefacts of the packages it depends on (turbo builds them first through `^build`),
// so a lane that runs those tests with pnpm directly must build them first; this guard makes a
// missing build fail with a clear message instead of a confusing test failure.
//
// Every export target must be a file, and every alternative of a fallback array must exist
// (stricter than Node, which takes the first that resolves). A pattern target
// (`./dist/tokens.*.css`) must match at least one file in its folder, so a pattern export is never
// skipped. Only a `*` in the file name is supported: a `*` in a folder segment is reported as
// unsupported. Every case the guard cannot prove built fails closed, a filesystem error too: it is
// reported with the export and its errno (ENOTDIR: a parent of the path is a file).
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

// ENOENT means "not built"; any other error (ENOTDIR, EACCES, ELOOP, ENAMETOOLONG, ...) goes up to
// main, which reports it. Not `throwIfNoEntry: false`: from Node 24 on it hides ENOTDIR too.
function unlessNoEntry(probe, absent) {
  try {
    return probe();
  } catch (err) {
    if (err.code === "ENOENT") return absent;
    throw err;
  }
}

function isFile(path) {
  return unlessNoEntry(() => statSync(path).isFile(), false);
}

function present(dir, target) {
  if (!target.includes("*")) return isFile(join(dir, target));
  const folder = join(dir, dirname(target));
  const escaped = basename(target)
    .replace(/[.+?^${}()|[\]\\]/g, "\\$&")
    .replaceAll("*", ".+");
  const pattern = new RegExp(`^${escaped}$`);
  const names = unlessNoEntry(() => readdirSync(folder), []).filter((name) => pattern.test(name));
  // Every match is checked (not `some`), so an error on any of them fails in any listing order.
  return names.map((name) => isFile(join(folder, name))).includes(true);
}

function exportsOf(dir) {
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
  } catch (err) {
    console.error(`${CODE}: cannot read ${join(dir, "package.json")}: ${err.message}`);
    process.exit(1);
  }
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    console.error(`${CODE}: ${join(dir, "package.json")} is not a JSON object`);
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
  const unsupported = [];
  const failed = [];
  for (const dir of dirs) {
    for (const target of exportsOf(dir)) {
      const file = join(dir, target);
      if (dirname(target).includes("*")) {
        unsupported.push(file);
        continue;
      }
      try {
        if (!present(dir, target)) missing.push(file);
      } catch (err) {
        failed.push(`${file}: ${err.message}`);
      }
    }
  }
  if (unsupported.length > 0) {
    console.error(
      `${CODE}: unsupported pattern exports (a "*" is supported in the file name only):`,
    );
    for (const file of unsupported) console.error(`  ${file}`);
  }
  if (missing.length > 0) {
    console.error(
      `${CODE}: built exports are missing; build the workspace packages first ` +
        '(pnpm --filter "@candleviewer/web^..." run build):',
    );
    for (const file of missing) console.error(`  ${file}`);
  }
  if (failed.length > 0) {
    console.error(`${CODE}: cannot check built exports, the filesystem returned an error:`);
    for (const line of failed) console.error(`  ${line}`);
  }
  if (unsupported.length > 0 || missing.length > 0 || failed.length > 0) process.exit(1);
  console.log(`check_built_exports: OK (${dirs.join(", ")})`);
}

main(process.argv.slice(2));
