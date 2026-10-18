#!/usr/bin/env node
// Generated-file guard (E02-T03 acceptance criterion #3, #2743).
// Every file under src/generated/ must start with the GENERATED FILE header and, once
// `pnpm generate` has recorded what it wrote (update-manifest.mjs, in the git-ignored
// .cache/generated-manifest.json), still match those hashes or the copy committed at HEAD: an
// edit that is neither fails here and points the author at `pnpm generate`. The record does not
// move with git, so content git wrote since the last generate (pull, rebase, checkout, merge) is
// accepted when it is exactly HEAD's blob. Without a recorded manifest (a fresh clone, CI) only
// the headers are checked, and the output says so. A committed hand edit is what CI's `gen`
// gate catches: it regenerates and diffs (tools/ci/check_gen_freshness.py, `make gen-check`).
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
const generatedDir = join(packageRoot, "src", "generated");
const manifestPath = join(packageRoot, ".cache", "generated-manifest.json");
const HEADER_MARKER = "GENERATED FILE — DO NOT EDIT BY HAND";

function listFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...listFiles(full));
    } else {
      out.push(full);
    }
  }
  return out;
}

function sha256(content) {
  // Line-ending agnostic: a Windows checkout may present CRLF while the manifest
  // was recorded from LF content. Only bytes, never EOL style, decide "hand-edited".
  const normalised = content.split("\r\n").join("\n");
  return createHash("sha256").update(normalised).digest("hex");
}

/**
 * The files among `rels` (paths under src/generated/) that hold exactly the blob HEAD has for
 * them: git wrote them, not a hand edit. Empty when git cannot tell (no repository, no HEAD).
 */
function matchingHead(rels) {
  if (rels.length === 0) return new Set();
  // Find the repository from src/generated/ itself, also when a git hook exported GIT_DIR.
  const env = { ...process.env };
  for (const name of ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"]) delete env[name];
  const git = (args) => spawnSync("git", args, { cwd: generatedDir, env, encoding: "utf8" });
  const tree = git(["ls-tree", "-r", "-z", "HEAD", "--", "."]);
  if (tree.status !== 0) return new Set();
  const head = new Map(); // path relative to src/generated/ -> blob id
  for (const entry of tree.stdout.split("\0")) {
    const tab = entry.indexOf("\t");
    if (tab !== -1) head.set(entry.slice(tab + 1), entry.slice(0, tab).split(" ")[2]);
  }
  const tracked = rels.filter((rel) => head.has(rel));
  if (tracked.length === 0) return new Set();
  // Paths as arguments: `--stdin-paths` would ignore the src/generated/ prefix.
  const hashed = git(["hash-object", "--", ...tracked]);
  if (hashed.status !== 0) return new Set();
  const blobs = hashed.stdout.trim().split("\n");
  return new Set(tracked.filter((rel, i) => blobs[i] === head.get(rel)));
}

function main() {
  const files = listFiles(generatedDir);
  const manifest = existsSync(manifestPath)
    ? JSON.parse(readFileSync(manifestPath, "utf8"))
    : undefined;
  const errors = [];
  const changed = new Map(); // rel -> why it differs from the last generate's record

  for (const file of files) {
    const rel = relative(generatedDir, file).replace(/\\/g, "/");
    const content = readFileSync(file, "utf8");
    if (rel === ".manifest.json") {
      errors.push(`${rel}: no longer committed (#2743). Run \`pnpm generate\`, which removes it.`);
      continue;
    }
    if (!content.includes(HEADER_MARKER)) {
      errors.push(`${rel}: missing the "${HEADER_MARKER}" header.`);
      continue;
    }
    if (manifest === undefined) continue;
    const expected = manifest[rel];
    if (!expected) {
      changed.set(
        rel,
        "not recorded by the last `pnpm generate`, nor HEAD's copy; run `pnpm generate`.",
      );
    } else if (expected !== sha256(content)) {
      changed.set(
        rel,
        "hash mismatch (hand-edited?): matches neither the last `pnpm generate` nor HEAD's copy. " +
          "Run `pnpm generate` instead of editing generated files.",
      );
    }
  }
  const fromGit = matchingHead([...changed.keys()]);
  for (const [rel, problem] of changed) {
    if (!fromGit.has(rel)) errors.push(`${rel}: ${problem}`);
  }

  if (errors.length > 0) {
    console.error("[generated-guard] FAILED:\n" + errors.map((e) => `  - ${e}`).join("\n"));
    process.exit(1);
  }
  if (manifest === undefined) {
    console.log(
      `[generated-guard] OK (${files.length} file(s), headers only: no ${relative(packageRoot, manifestPath)} yet; \`pnpm generate\` records one).`,
    );
    return;
  }
  const viaGit = fromGit.size > 0 ? `; git has since written ${fromGit.size}, matching HEAD` : "";
  console.log(
    `[generated-guard] OK (${files.length} file(s) verified against the last generate${viaGit}).`,
  );
}

main();
