#!/usr/bin/env node
// E03-T02 SR-138: after `pnpm install --frozen-lockfile --ignore-scripts`,
// explicitly (re)run the install step of each package on the small, reviewed
// allowlist in tools/ci/allowed-postinstall.json — instead of flipping
// `ignore-scripts` off repo-wide. Mirrors the exception already documented
// in `pnpm-workspace.yaml`'s `allowBuilds` block.
//
// An entry without `run` gets `pnpm rebuild <name>`: its own lifecycle scripts (esbuild's
// postinstall). An entry with `run` pins one `bin` of the package's own package.json, resolved from
// the `from` workspace, and the runner executes that file with node and no shell: Electron 42 and
// later ship their binary fetch as the `install-electron` bin, not as a postinstall (#1819). Every
// entry is checked, and every pinned bin found, before anything runs; a field the runner does not
// run, or a pinned bin the installed package no longer ships, fails the run.
//
// Usage: node tools/ci/run-allowed-postinstall.mjs

import { existsSync, readFileSync, statSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
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

function checkRun(name, run) {
  if (!isRecord(run)) {
    refuse(`${name}: run must be an object with ${RUN_KEYS.join(" and ")}`);
  }
  const keys = Object.keys(run).sort();
  if (keys.join() !== [...RUN_KEYS].sort().join()) {
    refuse(`${name}: run must have exactly ${RUN_KEYS.join(" and ")}, found: ${keys.join(", ")}`);
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
  const parsed = JSON.parse(readFileSync(path.join(root, ALLOWLIST), "utf8"));
  if (!Array.isArray(parsed.packages)) {
    throw new Error("tools/ci/allowed-postinstall.json is missing a packages[] array");
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
 * The file a `run` entry executes: the pinned bin of the package's own package.json, as installed
 * for the `from` workspace. Throws, naming the package, when the package is not installed there,
 * no longer ships that bin (a later release can move its install step), or points it outside the
 * package.
 */
export function resolvePinnedBin(root, entry) {
  const { name } = entry;
  const { bin, from } = entry.run;
  const workspace = path.join(root, from, "package.json");
  if (!existsSync(workspace)) {
    refuse(`${name}: run.from names no workspace (${from}/package.json is missing)`);
  }
  let manifestPath;
  try {
    manifestPath = createRequire(workspace).resolve(`${name}/package.json`);
  } catch (error) {
    refuse(
      `${name} is not installed for ${from} (${error.code ?? error.message}); run pnpm install`,
    );
  }
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const packageDir = path.dirname(manifestPath);
  const target = isRecord(manifest.bin) ? manifest.bin[bin] : undefined;
  if (typeof target !== "string") {
    refuse(
      `${name}@${manifest.version} has no "${bin}" in its package.json bin map: its install step ` +
        "moved, so review the entry before changing it",
    );
  }
  const file = path.resolve(packageDir, target);
  const inside = path.relative(packageDir, file);
  if (inside === "" || inside.split(path.sep)[0] === ".." || path.isAbsolute(inside)) {
    refuse(`${name}: bin "${bin}" points outside the package (${target})`);
  }
  if (!existsSync(file) || !statSync(file).isFile()) {
    refuse(`${name}@${manifest.version}: bin "${bin}" names ${target}, which the package lacks`);
  }
  return { file, packageDir, version: manifest.version };
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
    execFileSync("pnpm", ["rebuild", ...rebuild], {
      cwd: repoRoot,
      stdio: "inherit",
      shell: process.platform === "win32",
    });
  }
  for (const { entry, file, packageDir, version } of pinned) {
    const shown = path.relative(repoRoot, file);
    process.stdout.write(`running ${entry.name}@${version}'s ${entry.run.bin} bin (${shown})\n`);
    execFileSync(process.execPath, [file], { cwd: packageDir, stdio: "inherit" });
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
