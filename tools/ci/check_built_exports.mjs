#!/usr/bin/env node
// #3244: fail fast when a workspace package's built exports are missing. apps/web's tests import
// built artefacts of the packages it depends on (turbo builds them first through `^build`), so a
// lane that runs those tests with pnpm directly must build them first; this guard makes a missing
// build fail with a clear message instead of a confusing test failure.
//
// Usage: node tools/ci/check_built_exports.mjs <package-dir> [<package-dir> ...]
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

function targets(node, out) {
  if (typeof node === "string") {
    if (!node.includes("*")) out.push(node);
  } else if (node && typeof node === "object") {
    for (const value of Object.values(node)) targets(value, out);
  }
  return out;
}

function main(dirs) {
  if (dirs.length === 0) {
    console.error("usage: node tools/ci/check_built_exports.mjs <package-dir> [<package-dir> ...]");
    process.exit(2);
  }
  const missing = [];
  for (const dir of dirs) {
    const manifest = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
    const files = targets(manifest.exports ?? manifest.main ?? [], []);
    if (files.length === 0) {
      console.error(`CI-BUILD-001: ${dir}/package.json declares no exports to check`);
      process.exit(1);
    }
    for (const file of files) {
      if (!existsSync(join(dir, file))) missing.push(join(dir, file));
    }
  }
  if (missing.length > 0) {
    console.error(
      "CI-BUILD-001: built exports are missing; build the workspace packages first " +
        '(pnpm --filter "@candleviewer/web^..." run build):',
    );
    for (const file of missing) console.error(`  ${file}`);
    process.exit(1);
  }
  console.log(`check_built_exports: OK (${dirs.join(", ")})`);
}

main(process.argv.slice(2));
