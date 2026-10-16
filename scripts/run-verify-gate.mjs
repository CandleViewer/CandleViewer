#!/usr/bin/env node
// E02-T10: `pnpm verify` — the single local command that reproduces the PR
// gate (AGENTS.md §4 "Full local gate (what CI runs on a PR)"). Composes
// every gate named in CONSTITUTION.md §9's 20-row table, in table order,
// so drift between what a developer runs and what CI enforces is caught by
// `scripts/check-verify-gate-list.mjs` rather than discovered on a red PR.
//
// Gates that need infrastructure this workstation doesn't have (docker,
// CodeQL, Trivy, ...) print an explicit "runs in CI only" line instead of
// silently skipping (Technical notes / Security notes of the ticket this
// implements, E02-T10): an incomplete local gate must never look complete.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");

const results = [];

/**
 * @param {number} n
 * @param {string} name
 * @param {() => { status: "ran" | "ci-only", exitCode?: number }} fn
 */
function gate(n, name, fn) {
  console.log(`\n> verify [#${n} ${name}]`);
  const outcome = fn();
  results.push({ n, name, ...outcome });
  if (outcome.status === "ran" && outcome.exitCode !== 0) {
    printSummary();
    console.error(`\nverify: FAILED at gate #${n} "${name}" (exit ${outcome.exitCode})`);
    process.exit(outcome.exitCode ?? 1);
  }
}

/**
 * @param {string} command
 * @param {string[]} args
 * @param {import("node:child_process").SpawnSyncOptions} [opts]
 */
function run(command, args, opts = {}) {
  // Fail fast on a wrong cwd (#1564): a pytest run from the repo root collected
  // scripts/gh/tests and died with ModuleNotFoundError instead of mirroring CI.
  const cwd = opts.cwd ?? REPO_ROOT;
  if (
    command === "uv" &&
    args.includes("pytest") &&
    !existsSync(path.join(cwd, "pyproject.toml"))
  ) {
    console.error(`verify: pytest must run from a project dir with pyproject.toml (cwd=${cwd})`);
    return { status: "ran", exitCode: 1 };
  }
  const result = spawnSync(command, args, {
    cwd: REPO_ROOT,
    stdio: "inherit",
    shell: process.platform === "win32",
    ...opts,
  });
  return { status: "ran", exitCode: result.status ?? 1 };
}

function ciOnly(reason) {
  console.log(`  runs in CI only: ${reason}`);
  return { status: "ci-only" };
}

function printSummary() {
  console.log("\nverify: gate summary (CONSTITUTION.md §9 order)");
  for (const r of results) {
    const mark =
      r.status === "ci-only" ? "CI-ONLY" : r.exitCode === 0 ? "PASS" : `FAIL(${r.exitCode})`;
    console.log(`  #${r.n} ${r.name}: ${mark}`);
  }
}

// #2743: the local hand-edit guard compares packages/protocol/src/generated with what the last
// `pnpm generate` recorded in the git-ignored packages/protocol/.cache/, or with HEAD's copy for a
// file git wrote since (pull, rebase, checkout). It runs first: gate #2's typecheck regenerates,
// which would overwrite a hand edit without a word. Gate #19 is the required check (regenerate +
// diff); CI has no cache, so this guard is local only.
gate("pre", "generated-guard", () =>
  run("node", ["packages/protocol/scripts/check-generated-guard.mjs"]),
);
gate(1, "lint", () => run("pnpm", ["lint"]));
gate(2, "typecheck", () => run("pnpm", ["typecheck"]));
// Mirrors CI's py lane (.github/workflows/_job-py.yml) from services/api, so the
// repo-root scripts/ tests are not collected under the backend rootdir (#1564).
// Those are owned by the governance workflow and run as a second step here.
gate(3, "unit-backend", () => {
  const backend = run(
    "uv",
    [
      "run",
      "pytest",
      "-p",
      "no:cacheprovider",
      "-m",
      "not exchange_smoke and not (chaos and integration) and not roundtrip and not fuzz and not harness and not perf and not integration",
      "--ignore=tests/unit/ws/test_cvwb_perf.py",
    ],
    { cwd: path.join(REPO_ROOT, "services", "api") },
  );
  if (backend.exitCode !== 0) return backend;
  return run("uv", [
    "run",
    "--project",
    "services/api",
    "python",
    "-m",
    "pytest",
    "scripts/tests",
    "scripts/gh/tests",
    "-q",
    "--no-cov",
    "-p",
    "no:cacheprovider",
  ]);
});
gate(4, "unit-engine", () => run("pnpm", ["--filter", "@candleviewer/chart-engine", "test:cov"]));
gate(5, "unit-frontend", () =>
  run("pnpm", ["--filter", "@candleviewer/web", "--filter", "@candleviewer/ui", "test:cov"]),
);
gate(6, "contract", () => {
  const backend = run(
    "uv",
    ["run", "pytest", "tests/contract", "-m", "not integration", "--no-cov"],
    {
      cwd: path.join(REPO_ROOT, "services", "api"),
    },
  );
  if (backend.exitCode !== 0) return backend;
  return run("pnpm", ["--filter", "@candleviewer/protocol", "test"]);
});
gate(7, "integration", () => ciOnly("needs the docker compose stack (Postgres/QuestDB)"));
gate(8, "e2e-smoke", () => ciOnly("needs a seeded stack + headless browser install"));
gate(9, "a11y", () => ciOnly("axe-core sweep runs against the seeded Storybook/route stack in CI"));
gate(10, "sast", () => ciOnly("CodeQL + Semgrep + Bandit run in CI (no local CodeQL toolchain)"));
gate(11, "sca", () => run("uv", ["run", "--project", "services/api", "pip-audit"]));
gate(12, "secrets-scan", () => run("gitleaks", ["protect", "--staged", "--redact"]));
gate(13, "container-scan", () => ciOnly("Trivy runs against the built image in CI"));
gate(14, "license-check", () =>
  ciOnly(
    "licence collection (tools/ci/collect_licenses.py) needs pip-licenses/license-checker/pnpm-licenses input files produced by the CI dependency-install step",
  ),
);
gate(15, "bundle-size", () => run("pnpm", ["size"]));
gate(16, "engine-bench", () => run("pnpm", ["--filter", "@candleviewer/chart-engine", "bench"]));
gate(17, "migrations", () =>
  ciOnly("Alembic round-trip needs the docker compose Postgres service"),
);
gate(18, "architecture", () => run("pnpm", ["arch"]));
gate(19, "generated-code-check", () => run("python", ["tools/ci/check_gen_freshness.py"]));
gate(20, "pr-metadata", () =>
  ciOnly("branch/PR-metadata checks need an open PR; run `pnpm check:branch-name` locally"),
);

gate("guard", "threshold-guard (C-9.4)", () => run("python", ["tools/ci/quality_gates.py"]));

printSummary();
console.log("\nverify: all runnable gates passed.");
