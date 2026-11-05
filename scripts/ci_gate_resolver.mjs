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
//   - a light-deferred lane (LIGHT_DEFERRED) applicable and skipped on a pull_request without the
//     `ci:full` label -> ok, reported as "deferred to the merge group" (#5746): a pull request's
//     run is the light job set, draft or not, and every merge-group run, like a `ci:full`
//     pull request's, requires the lane. The label flag is read on pull_request only, and only the
//     boolean `true` counts; with it, or on any other event or with the event unknown, the lane is
//     a lane like the rest. The flag is also true on a pull request that touches a C-10.2 path:
//     pr.yml runs the full set there automatically (#5785).
//   - the deferral holds only while `changed-paths` confirmed an active merge queue rule on `main`
//     (MERGE_QUEUE, the boolean `true` only): the merge group is then the full run every change
//     passes. Without it (the rule gone, or the API unread) a light run's skipped heavy lane fails
//     CI-GATE-002 with the queue named, so a pull request cannot merge on the light set (#5785).
//   - a draft pull request never passes (CI-GATE-005, #5506), whatever the lanes say, `ci:full`
//     or not: its `ci-required` can pass only once it is ready for review. merge_group,
//     workflow_dispatch and a ready pull request are judged on their lanes.

import { appendFileSync, realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";

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
// Lanes whose job in .github/workflows/pr.yml runs on a heavy run only (its `if:` ends in
// `&& (github.event_name == 'merge_group' || github.event_name == 'workflow_dispatch' ||
// contains(github.event.pull_request.labels.*.name, 'ci:full'))`, #5746): change that and this
// set together. A merge group, a train and a `ci:full` pull request run them; every other pull
// request defers them to the merge group. `integration` is gated the same way but is not listed:
// a pull request's run skips it on every PR, labelled or not, and MERGE_GROUP_ONLY defers that.
const LIGHT_DEFERRED = new Set([
  "e2e",
  "a11y",
  "engine-bench",
  "rule-roundtrip",
  "contract",
  "migrations",
  "security",
  "coverage-thresholds",
]);
const DRAFT_GATE_CODE = "CI-GATE-005";
const DRAFT_GATE_REASON = "draft pull request: ci-required passes once it is ready for review";
const LIGHT_DEFERRED_REASON = "deferred to the merge group";
const NO_QUEUE_REASON =
  "the merge queue on main is not confirmed, so a light run defers nothing: label the PR ci:full";
// Lanes whose not-applicable state is named in the output (E03-T14, Gherkin S1): a diff outside
// the engine and protocol filters skips engine-bench, and the reader sees that, not a silent pass.
const REPORT_NA = new Set(["engine-bench"]);
const NOT_APPLICABLE_REASON = "no engine or protocol path changed";

/**
 * @param {string} name @param {LaneInput} input @param {string} [event]
 * @param {boolean} [full] whether the pull request carries the `ci:full` label or touches a C-10.2
 *   path (PR_FULL); read on pull_request only, and only the boolean `true` keeps a lane required (a
 *   truthy string, say, does not)
 * @param {boolean} [queue] whether an active merge queue rule protects `main` (MERGE_QUEUE); only
 *   the boolean `true` lets a light run defer a lane, so unknown fails closed
 * @returns {LaneOutcome}
 */
function evaluateLane(name, { applicable, result }, event = "", full = false, queue = false) {
  if (
    applicable &&
    result === "skipped" &&
    event === "pull_request" &&
    MERGE_GROUP_ONLY.has(name)
  ) {
    return { ok: true, code: null, reason: null, deferred: DEFERRED_REASON };
  }
  if (
    applicable &&
    result === "skipped" &&
    event === "pull_request" &&
    full !== true &&
    LIGHT_DEFERRED.has(name)
  ) {
    if (queue === true) {
      return { ok: true, code: null, reason: null, deferred: LIGHT_DEFERRED_REASON };
    }
    return {
      ok: false,
      code: "CI-GATE-002",
      reason: `gate misconfiguration: ${name} applicable but skipped; ${NO_QUEUE_REASON}`,
    };
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
 * @param {boolean} [draft] whether the pull request is a draft (PR_DRAFT); unknown is false
 * @param {boolean} [full] whether the pull request carries `ci:full` or touches a C-10.2 path
 *   (PR_FULL); unknown is false
 * @param {boolean} [queue] whether `main` has an active merge queue rule (MERGE_QUEUE); unknown is
 *   false
 * @returns {{ conclusion: "success" | "failure", failures: LaneOutcome[], deferred: { lane: string, reason: string }[], notApplicable: { lane: string, reason: string }[] }}
 */
export function resolveGate(lanes, event = "", draft = false, full = false, queue = false) {
  const failures = [];
  const deferred = [];
  const notApplicable = [];
  for (const [name, input] of Object.entries(lanes)) {
    const outcome = evaluateLane(name, input, event, full, queue);
    if (!outcome.ok) failures.push(outcome);
    if (outcome.deferred) deferred.push({ lane: name, reason: outcome.deferred });
    if (!input.applicable && REPORT_NA.has(name))
      notApplicable.push({ lane: name, reason: NOT_APPLICABLE_REASON });
  }
  if (event === "pull_request" && draft === true) {
    failures.push({ ok: false, code: DRAFT_GATE_CODE, reason: DRAFT_GATE_REASON });
  }
  return {
    conclusion: failures.length === 0 ? "success" : "failure",
    failures,
    deferred,
    notApplicable,
  };
}

export {
  evaluateLane,
  MERGE_GROUP_ONLY,
  LIGHT_DEFERRED,
  LIGHT_DEFERRED_REASON,
  NO_QUEUE_REASON,
  DRAFT_GATE_CODE,
  DRAFT_GATE_REASON,
  REPORT_NA,
};

// --- CLI entry point (used by actions/github-script step) -----------------
// Reads lane definitions from argv[2] as a JSON string:
//   { "js": {"applicable": true, "result": "success"}, ... }
// the event from GITHUB_EVENT_NAME, which the runner sets in every step, and whether the pull
// request is a draft from PR_DRAFT ("true" / "false", empty off a pull request), which the
// `ci-required` step sets from `github.event.pull_request.draft`, and whether it carries the
// `ci:full` label or touches a C-10.2 path from PR_FULL ("true" / "false"), and whether `main` has
// an active merge queue rule from MERGE_QUEUE ("true" / "false", `changed-paths`' `queue` output);
// all three read on a pull_request only.
// Exits 0 on success, 1 on failure, printing each failure reason to stderr.
async function main() {
  const raw = process.argv[2];
  if (!raw) {
    console.error("usage: node ci_gate_resolver.mjs '<lanes-json>'");
    process.exit(2);
  }
  /** @type {Record<string, LaneInput>} */
  const lanes = JSON.parse(raw);
  const { conclusion, failures, deferred, notApplicable } = resolveGate(
    lanes,
    process.env.GITHUB_EVENT_NAME ?? "",
    process.env.PR_DRAFT === "true",
    process.env.PR_FULL === "true",
    process.env.MERGE_QUEUE === "true",
  );
  for (const f of failures) {
    console.error(`${f.code}: ${f.reason}`);
  }
  for (const { lane, reason } of deferred) {
    console.log(`::notice title=${lane} deferred::${lane}: skipped — ${reason}`);
  }
  for (const { lane, reason } of notApplicable) {
    console.log(`::notice title=${lane} not applicable::${lane}: not applicable — ${reason}`);
  }
  const summary = process.env.GITHUB_STEP_SUMMARY;
  if (summary && notApplicable.length > 0) {
    const rows = notApplicable.map(
      ({ lane, reason }) => `| ${lane} | not applicable | ${reason} |`,
    );
    appendFileSync(
      summary,
      [
        "## ci-required: lanes not applicable",
        "",
        "| Lane | State | Why |",
        "| --- | --- | --- |",
        ...rows,
        "",
      ].join("\n"),
    );
  }
  console.log(`ci-required conclusion: ${conclusion}`);
  process.exit(conclusion === "success" ? 0 : 1);
}

// Only run the CLI when this file is the process entry point (not when
// imported by the vitest suite): the module's real path against the script argument's.
function isEntryPoint() {
  const script = process.argv[1];
  if (!script) return false;
  try {
    return realpathSync(fileURLToPath(import.meta.url)) === realpathSync(script);
  } catch {
    return false;
  }
}

if (isEntryPoint()) {
  main();
}
