#!/usr/bin/env node
// E03-T04 follow-up: record which workspace packages Turborepo actually
// scheduled `test:cov` for in this lane, given the `...[origin/main]`
// affected-graph filters. Unaffected packages never produce a
// `coverage/lcov.info`, so `tools/ci/coverage_gate.py` needs this manifest
// to tell "not affected by this change set" (N/A) apart from "affected but no
// report" (CI-COV-003). The manifest is uploaded inside the lane's coverage
// artifact as `affected-packages.txt`, one repo-relative directory per line
// (forward slashes), e.g. `packages/chart-engine`.
//
// Usage: node tools/ci/turbo-affected-packages.mjs <out-file> -- <turbo filter args...>
//
// Fail-closed: any error exits non-zero so the lane fails rather than silently
// uploading an empty manifest that would make every package N/A.

import { execFileSync } from "node:child_process";
import {
  closeSync,
  fstatSync,
  mkdtempSync,
  openSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const BACKSLASH = String.fromCharCode(92);

export function affectedDirectories(dryRunJson, task = "test:cov") {
  const tasks = Array.isArray(dryRunJson.tasks) ? dryRunJson.tasks : [];
  const dirs = new Set();
  for (const t of tasks) {
    if (t.task !== task || typeof t.directory !== "string") continue;
    dirs.add(t.directory.split(BACKSLASH).join("/"));
  }
  return [...dirs].sort();
}

function main(argv) {
  const sep = argv.indexOf("--");
  if (sep < 1) {
    process.stderr.write("usage: turbo-affected-packages.mjs <out-file> -- <turbo filter args>\n");
    return 2;
  }
  const outFile = argv[sep - 1];
  const filterArgs = argv.slice(sep + 1);
  // The dry-run JSON lists every input hash of every scheduled package and outgrows Node's 1 MiB
  // pipe buffer (ENOBUFS, #5596): turbo writes to a private temp file instead, read back after.
  const dir = mkdtempSync(join(tmpdir(), "turbo-dry-run-"));
  const file = join(dir, "dry-run.json");
  let raw;
  try {
    const fd = openSync(file, "wx");
    try {
      execFileSync("pnpm", ["turbo", "run", "test:cov", ...filterArgs, "--dry-run=json"], {
        stdio: ["ignore", fd, "inherit"],
        shell: process.platform === "win32",
      });
    } catch (err) {
      const why = err.status ?? err.signal ?? err.code ?? "unknown";
      const bytes = fstatSync(fd).size;
      process.stderr.write(
        `turbo-affected-packages: turbo dry-run failed (${why}; ${bytes} bytes read)\n`,
      );
      return 1;
    } finally {
      closeSync(fd);
    }
    raw = readFileSync(file, "utf8");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    // never the payload: a parse error would quote it (one line can be the whole dry-run)
    process.stderr.write(
      `turbo-affected-packages: turbo dry-run JSON invalid (${Buffer.byteLength(raw)} bytes)\n`,
    );
    return 1;
  }
  const dirs = affectedDirectories(parsed);
  writeFileSync(outFile, dirs.length ? dirs.join("\n") + "\n" : "", "utf8");
  process.stdout.write(
    `turbo-affected-packages: ${dirs.length} package(s) scheduled for test:cov -> ${outFile}\n`,
  );
  for (const d of dirs) process.stdout.write(`  ${d}\n`);
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main(process.argv.slice(2)));
}
