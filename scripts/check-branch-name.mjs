#!/usr/bin/env node
// Validate the current (or a given) branch name against the prefixes in
// docs/plan/01-sdlc-and-branching.md §6.1. Used by the pre-push hook and
// reusable by E03's `pr-metadata` CI job (docs/plan/backlog E02-T07).
//
// Usage:
//   node scripts/check-branch-name.mjs [branch-name]
// If no branch name is given, the current git branch (via `git rev-parse
// --abbrev-ref HEAD`) is checked. Exits 0 when valid, 1 otherwise.

import { execFileSync } from "node:child_process";

// Keep in sync with docs/plan/01-sdlc-and-branching.md §6.1. `main` and
// `release/*` are protected/automation-only branches and are always allowed
// through this check (nobody pushes directly to them via a dev workstation
// hook in the first place; CI branch-protection is the real gate there).
// `train/*` is the orchestrator's merge train (§7, #3783): pushed only to be
// validated by one dispatched `pr.yml` run, never a PR head.
const ALLOWED_PREFIXES = ["feat/", "fix/", "chore/", "design/", "spike/", "hotfix/"];
const ALWAYS_ALLOWED = new Set(["main"]);
const ALWAYS_ALLOWED_PREFIXES = ["release/", "train/"];

export function isValidBranchName(name) {
  if (typeof name !== "string" || name.length === 0) return false;
  if (ALWAYS_ALLOWED.has(name)) return true;
  if (ALWAYS_ALLOWED_PREFIXES.some((p) => name.startsWith(p))) return true;
  return ALLOWED_PREFIXES.some((prefix) => {
    if (!name.startsWith(prefix)) return false;
    const rest = name.slice(prefix.length);
    return rest.length > 0;
  });
}

function getCurrentBranch() {
  return execFileSync("git", ["rev-parse", "--abbrev-ref", "HEAD"], {
    encoding: "utf8",
  }).trim();
}

function main() {
  const arg = process.argv[2];
  const branch = arg ?? getCurrentBranch();

  if (isValidBranchName(branch)) {
    process.exit(0);
  }

  process.stderr.write(
    [
      `error: branch name "${branch}" does not match the branch-naming pattern.`,
      "",
      "Allowed prefixes (docs/plan/01-sdlc-and-branching.md §6.1):",
      ...ALLOWED_PREFIXES.map((p) => `  - ${p}<short-description>`),
      "",
      "Example: feat/of-42-footprint-cells",
      "",
      "Emergency bypass: git push --no-verify (CI still enforces this server-side).",
      "",
    ].join("\n"),
  );
  process.exit(1);
}

// Only run as a CLI when invoked directly (not when imported for tests).
const isMain = process.argv[1] && process.argv[1].endsWith("check-branch-name.mjs");
if (isMain) {
  main();
}
