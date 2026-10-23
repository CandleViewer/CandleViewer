#!/usr/bin/env node
// E03-T02 SR-138: after `pnpm install --frozen-lockfile --ignore-scripts`,
// explicitly (re)run the install step of each package on the small, reviewed
// allowlist in tools/ci/allowed-postinstall.json — instead of flipping
// `ignore-scripts` off repo-wide. Mirrors the exception already documented
// in `pnpm-workspace.yaml`'s `allowBuilds` block. That file's `ignoreScripts: true` (C-12.3) also
// applies to `pnpm rebuild`, which would then build nothing, so the rebuild passes
// --no-ignore-scripts: the allowlist names what may build and `allowBuilds` has the last word.
//
// An entry without `run` gets `pnpm rebuild <name>`: its own lifecycle scripts (esbuild's
// postinstall). An entry with `run` pins one `bin` of the package's own package.json, read from
// exactly `<from>/node_modules/<name>` (its link resolved; no walk up the tree, no NODE_PATH), and
// the runner executes that file with node and no shell: Electron 42 and later ship their binary
// fetch as the `install-electron` bin, not as a postinstall (#1819). Every entry is checked, and
// every pinned bin found, before anything runs; a field the runner does not run, or a pinned bin
// the installed package no longer ships or that resolves outside it, fails the run.
//
// Usage: node tools/ci/run-allowed-postinstall.mjs

import { existsSync, readFileSync, realpathSync, statSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repoRoot = path.resolve(fileURLToPath(import.meta.url), "..", "..", "..");
const ALLOWLIST = "tools/ci/allowed-postinstall.json";
// npm's package-name grammar (optional scope), and a bare bin name: no path, no shell syntax.
const PACKAGE_NAME = /^(?:@[a-z0-9][a-z0-9._-]*\/)?[a-z0-9][a-z0-9._-]*$/;
const BIN_NAME = /^[a-z0-9][a-z0-9._-]*$/;
const ENTRY_KEYS = ["name", "run", "reason", "reviewedBy"];
const RUN_KEYS = ["bin", "from"];

function refuse(message) {
  throw new Error(`${ALLOWLIST}: ${message}`);
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** A workspace path relative to the repo root: forward slashes, no `.` or `..` segment. */
function isWorkspacePath(value) {
  return (
    typeof value === "string" &&
    value !== "" &&
    !value.startsWith("/") &&
    !value.includes("\\") &&
    value.split("/").every((segment) => segment !== "" && segment !== "." && segment !== "..")
  );
}

/** True when `file` lies strictly inside `dir` (both already in the same form). */
function isInside(dir, file) {
  const inside = path.relative(dir, file);
  return inside !== "" && inside.split(path.sep)[0] !== ".." && !path.isAbsolute(inside);
}

function checkRun(name, run) {
  if (!isRecord(run)) {
    refuse(`${name}: run must be an object with ${RUN_KEYS.join(" and ")}`);
  }
  const keys = Object.keys(run).sort();
  if (keys.join() !== [...RUN_KEYS].sort().join()) {
    const found = keys.length > 0 ? keys.join(", ") : "none";
    refuse(`${name}: run must have exactly ${RUN_KEYS.join(" and ")}, found: ${found}`);
  }
  if (typeof run.bin !== "string" || !BIN_NAME.test(run.bin)) {
    refuse(`${name}: run.bin must be a bare bin name of the package`);
  }
  if (!isWorkspacePath(run.from)) {
    refuse(`${name}: run.from must be a workspace path inside the repository`);
  }
  return { bin: run.bin, from: run.from };
}

/** The allowlist's entries, each checked against the reviewed shape. */
export function loadEntries(root) {
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(path.join(root, ALLOWLIST), "utf8"));
  } catch (error) {
    refuse(`cannot be read as JSON: ${error.message}`);
  }
  if (!isRecord(parsed) || !Array.isArray(parsed.packages)) {
    refuse("is missing a packages[] array");
  }
  const seen = new Set();
  return parsed.packages.map((entry, index) => {
    if (!isRecord(entry)) {
      refuse(`entry ${index} is not an object`);
    }
    const unknown = Object.keys(entry).filter((key) => !ENTRY_KEYS.includes(key));
    if (unknown.length > 0) {
      refuse(`entry ${index} has fields the runner does not run: ${unknown.join(", ")}`);
    }
    const { name } = entry;
    if (typeof name !== "string" || !PACKAGE_NAME.test(name)) {
      refuse(`entry ${index} has no valid package name`);
    }
    if (seen.has(name)) {
      refuse(`${name} is listed twice`);
    }
    seen.add(name);
    return entry.run === undefined ? { name } : { name, run: checkRun(name, entry.run) };
  });
}

/** The package names on the allowlist. */
export function loadAllowlist(root) {
  return loadEntries(root).map((entry) => entry.name);
}

/**
 * The file a `run` entry executes: the pinned bin of the package's own package.json, read from
 * exactly `<from>/node_modules/<name>/package.json` with its link resolved, never found by walking
 * up the tree or through NODE_PATH (so an `exports` map does not apply). Throws, naming the
 * package, when it is not installed there, no longer ships that bin (a later release can move its
 * install step), or the bin, its links resolved, lies outside the package.
 */
export function resolvePinnedBin(root, entry) {
  const { name } = entry;
  const { bin, from } = entry.run;
  if (!existsSync(path.join(root, from, "package.json"))) {
    refuse(`${name}: run.from names no workspace (${from}/package.json is missing)`);
  }
  const linked = path.join(root, from, "node_modules", ...name.split("/"), "package.json");
  if (!existsSync(linked)) {
    const missing = path.relative(root, linked).split(path.sep).join("/");
    refuse(`${name} is not installed for ${from} (${missing} is missing); run pnpm install`);
  }
  const manifestPath = realpathSync(linked);
  const packageDir = path.dirname(manifestPath);
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const target = isRecord(manifest.bin) ? manifest.bin[bin] : undefined;
  if (typeof target !== "string") {
    refuse(
      `${name}@${manifest.version} has no "${bin}" in its package.json bin map: its install step ` +
        "moved, so review the entry before changing it",
    );
  }
  const file = path.resolve(packageDir, target);
  if (!isInside(packageDir, file)) {
    refuse(`${name}: bin "${bin}" points outside the package (${target})`);
  }
  if (!existsSync(file)) {
    refuse(`${name}@${manifest.version}: bin "${bin}" names ${target}, which the package lacks`);
  }
  const realFile = realpathSync(file);
  if (!isInside(realpathSync(packageDir), realFile)) {
    refuse(`${name}: bin "${bin}" points outside the package through a link (${target})`);
  }
  if (!statSync(realFile).isFile()) {
    refuse(`${name}@${manifest.version}: bin "${bin}" names ${target}, which is not a file`);
  }
  return { file: realFile, packageDir, version: manifest.version };
}

function main() {
  const entries = loadEntries(repoRoot);
  if (entries.length === 0) {
    process.stdout.write("no allowlisted postinstall packages configured\n");
    return;
  }
  const rebuild = entries.filter((entry) => entry.run === undefined).map((entry) => entry.name);
  const pinned = entries
    .filter((entry) => entry.run !== undefined)
    .map((entry) => ({ entry, ...resolvePinnedBin(repoRoot, entry) }));

  if (rebuild.length > 0) {
    process.stdout.write(`running pnpm rebuild for allowlisted packages: ${rebuild.join(", ")}\n`);
    execFileSync("pnpm", ["rebuild", "--no-ignore-scripts", ...rebuild], {
      cwd: repoRoot,
      stdio: "inherit",
      shell: process.platform === "win32",
    });
  }
  for (const { entry, file, packageDir, version } of pinned) {
    const label = `${entry.name}@${version}'s ${entry.run.bin} bin`;
    process.stdout.write(`running ${label} (${path.relative(repoRoot, file)})\n`);
    const started = Date.now();
    execFileSync(process.execPath, [file], { cwd: packageDir, stdio: "inherit" });
    process.stdout.write(`${label} done in ${((Date.now() - started) / 1000).toFixed(1)}s\n`);
  }
}

const isMain = process.argv[1] && process.argv[1].endsWith("run-allowed-postinstall.mjs");
if (isMain) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`run-allowed-postinstall: ${error.message}\n`);
    process.exitCode = 1;
  }
}
