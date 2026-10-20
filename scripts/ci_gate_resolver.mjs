#!/usr/bin/env node
// ci-required resolver (ADR-0013-ci-pipeline.md binding rule 2, E03-T01).
//
// Computes the final conclusion for the `ci-required` gate job from the
// `changed-paths` filter outputs and each lane's `needs.<lane>.result`.
// Exported as a pure function so it can be unit-tested without GitHub
// Actions context; the CLI entry point below is what `actions/github-script`
// invokes from `.github/workflows/pr.yml`.
//
// Rules:
//   - applicable (filter true) and result != 'success' -> fail (CI-GATE-001)
//   - not applicable (filter false) and result == 'skipped' -> ok
//   - applicable (filter true) and result == 'skipped' -> fail (CI-GATE-002),
//     "gate misconfiguration: <lane> applicable but skipped"
//   - not applicable and result != 'skipped' (e.g. it ran anyway) -> ok,
//     a lane running unnecessarily is not a gate failure.
//   - a merge-group-only lane (MERGE_GROUP_ONLY) applicable and skipped on a pull_request -> ok,
//     reported as deferred (#3881): its workflow skips it there by design and the merge queue
//     requires it. On any other event, or with the event unknown, it is a lane like the rest.

/**
 * @typedef {"success"|"failure"|"cancelled"|"skipped"} LaneResult
 * @typedef {{ applicable: boolean, result: LaneResult }} LaneInput
 * @typedef {{ ok: boolean, code: string | null, reason: string | null, deferred?: string }} LaneOutcome
 */

// Lanes whose workflow runs them on the merge queue's groups and on merge trains, never on a pull
// request's own run (#3881). Their job's `if:` reads `github.event_name != 'pull_request'`
// (.github/workflows/_job-integration.yml): change that and this set together.
const MERGE_GROUP_ONLY = new Set(["integration"]);
const DEFERRED_REASON = "runs on the merge group";

/** @param {string} name @param {LaneInput} input @param {string} [event] @returns {LaneOutcome} */
function evaluateLane(name, { applicable, result }, event = "") {
  if (
    applicable &&
    result === "skipped" &&
    event === "pull_request" &&
    MERGE_GROUP_ONLY.has(name)
  ) {
    return { ok: true, code: null, reason: null, deferred: DEFERRED_REASON };
  }
  if (applicable && result === "skipped") {
    return {
      ok: false,
      code: "CI-GATE-002",
      reason: `gate misconfiguration: ${name} applicable but skipped`,
    };
  }
  if (applicable && result !== "success") {
    return {
      ok: false,
      code: "CI-GATE-001",
      reason: `${name} required and not successful (result: ${result})`,
    };
  }
  return { ok: true, code: null, reason: null };
}

/**
 * @param {Record<string, LaneInput>} lanes
 * @param {string} [event] the workflow's event name (GITHUB_EVENT_NAME); unknown is ""
 * @returns {{ conclusion: "success" | "failure", failures: LaneOutcome[], deferred: { lane: string, reason: string }[] }}
 */
export function resolveGate(lanes, event = "") {
  const failures = [];
  const deferred = [];
  for (const [name, input] of Object.entries(lanes)) {
    const outcome = evaluateLane(name, input, event);
    if (!outcome.ok) failures.push(outcome);
    if (outcome.deferred) deferred.push({ lane: name, reason: outcome.deferred });
  }
  return {
    conclusion: failures.length === 0 ? "success" : "failure",
    failures,
    deferred,
  };
}

export { evaluateLane, MERGE_GROUP_ONLY };

// --- CLI entry point (used by actions/github-script step) -----------------
// Reads lane definitions from argv[2] as a JSON string:
//   { "js": {"applicable": true, "result": "success"}, ... }
// and the event from GITHUB_EVENT_NAME, which the runner sets in every step.
// Exits 0 on success, 1 on failure, printing each failure reason to stderr.
async function main() {
  const raw = process.argv[2];
  if (!raw) {
    console.error("usage: node ci_gate_resolver.mjs '<lanes-json>'");
    process.exit(2);
  }
  /** @type {Record<string, LaneInput>} */
  const lanes = JSON.parse(raw);
  const { conclusion, failures, deferred } = resolveGate(
    lanes,
    process.env.GITHUB_EVENT_NAME ?? "",
  );
  for (const f of failures) {
    console.error(`${f.code}: ${f.reason}`);
  }
  for (const { lane, reason } of deferred) {
    console.log(`::notice title=${lane} deferred::${lane}: skipped — ${reason}`);
  }
  console.log(`ci-required conclusion: ${conclusion}`);
  process.exit(conclusion === "success" ? 0 : 1);
}

// Only run the CLI when this file is the process entry point (not when
// imported by the vitest suite).
if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
