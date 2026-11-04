import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { afterAll, describe, expect, it } from "vitest";
import {
  DRAFT_GATE_CODE,
  DRAFT_GATE_REASON,
  evaluateLane,
  LIGHT_DEFERRED,
  LIGHT_DEFERRED_REASON,
  MERGE_GROUP_ONLY,
  NO_QUEUE_REASON,
  REPORT_NA,
  resolveGate,
} from "../../../scripts/ci_gate_resolver.mjs";

describe("evaluateLane", () => {
  /** @type {Array<["success"|"failure"|"cancelled"|"skipped", boolean, boolean, string|null]>} */
  const matrix = [
    // result, applicable, expectedOk, expectedCode
    ["success", true, true, null],
    ["success", false, true, null],
    ["failure", true, false, "CI-GATE-001"],
    ["failure", false, true, null],
    ["cancelled", true, false, "CI-GATE-001"],
    ["cancelled", false, true, null],
    ["skipped", true, false, "CI-GATE-002"],
    ["skipped", false, true, null],
  ];

  for (const [result, applicable, expectedOk, expectedCode] of matrix) {
    it(`result=${result} applicable=${applicable} -> ok=${expectedOk}`, () => {
      const outcome = evaluateLane("lane", { applicable, result });
      expect(outcome.ok).toBe(expectedOk);
      expect(outcome.code).toBe(expectedCode);
    });
  }
});

describe("resolveGate", () => {
  it("succeeds when every applicable lane succeeded and inapplicable ones skipped", () => {
    const { conclusion, failures } = resolveGate({
      js: { applicable: true, result: "success" },
      py: { applicable: false, result: "skipped" },
      engine: { applicable: false, result: "skipped" },
    });
    expect(conclusion).toBe("success");
    expect(failures).toEqual([]);
  });

  it("fails with CI-GATE-002 when an applicable lane is skipped (gate misconfiguration)", () => {
    const { conclusion, failures } = resolveGate({
      engine: { applicable: true, result: "skipped" },
    });
    expect(conclusion).toBe("failure");
    expect(failures).toHaveLength(1);
    expect(failures[0].code).toBe("CI-GATE-002");
    expect(failures[0].reason).toBe("gate misconfiguration: engine applicable but skipped");
  });

  it("fails with CI-GATE-001 when an applicable lane failed", () => {
    const { conclusion, failures } = resolveGate({
      py: { applicable: true, result: "failure" },
    });
    expect(conclusion).toBe("failure");
    expect(failures[0].code).toBe("CI-GATE-001");
  });

  it("fails with CI-GATE-001 when an applicable lane was cancelled", () => {
    const { conclusion, failures } = resolveGate({
      e2e: { applicable: true, result: "cancelled" },
    });
    expect(conclusion).toBe("failure");
    expect(failures[0].code).toBe("CI-GATE-001");
  });

  it("aggregates multiple failures across lanes", () => {
    const { conclusion, failures } = resolveGate({
      js: { applicable: true, result: "failure" },
      engine: { applicable: true, result: "skipped" },
      docs: { applicable: false, result: "skipped" },
    });
    expect(conclusion).toBe("failure");
    expect(failures).toHaveLength(2);
  });

  it("fails closed when changed-paths itself did not succeed, even if every filter-gated lane skipped (CI-GATE-001)", () => {
    // Regression for the fail-open bug: if `changed-paths` fails/cancels,
    // every filter output comes back empty ("false"), so js/py/security would
    // otherwise all read as inapplicable and skipped, letting ci-required pass
    // with none of them having run. `changed-paths` must be its own
    // always-applicable lane so that outcome is CI-GATE-001, not success.
    const { conclusion, failures } = resolveGate({
      "changed-paths": { applicable: true, result: "failure" },
      js: { applicable: false, result: "skipped" },
      py: { applicable: false, result: "skipped" },
      security: { applicable: false, result: "skipped" },
    });
    expect(conclusion).toBe("failure");
    expect(failures).toHaveLength(1);
    expect(failures[0].code).toBe("CI-GATE-001");
    expect(failures[0].reason).toContain("changed-paths");
  });

  it("docs-only PR: all code lanes inapplicable and skipped -> success", () => {
    const { conclusion } = resolveGate({
      js: { applicable: false, result: "skipped" },
      py: { applicable: false, result: "skipped" },
      contract: { applicable: false, result: "skipped" },
      e2e: { applicable: false, result: "skipped" },
      engine: { applicable: false, result: "skipped" },
    });
    expect(conclusion).toBe("success");
  });
});

// #3881: the compose integration lane runs on the merge group and on merge trains only.
describe("merge-group-only lanes", () => {
  const skipped = { applicable: true, result: "skipped" };

  it("is the integration lane and no other", () => {
    expect([...MERGE_GROUP_ONLY]).toEqual(["integration"]);
  });

  it("reads a skipped integration lane on a pull_request as deferred, not as CI-GATE-002", () => {
    expect(evaluateLane("integration", skipped, "pull_request")).toEqual({
      ok: true,
      code: null,
      reason: null,
      deferred: "runs on the merge group",
    });
    const { conclusion, failures, deferred } = resolveGate(
      { integration: skipped },
      "pull_request",
    );
    expect(conclusion).toBe("success");
    expect(failures).toEqual([]);
    expect(deferred).toEqual([{ lane: "integration", reason: "runs on the merge group" }]);
  });

  for (const event of ["merge_group", "workflow_dispatch", "push", ""]) {
    it(`still requires it on ${event || "an unknown event"} (CI-GATE-002)`, () => {
      const { conclusion, failures, deferred } = resolveGate({ integration: skipped }, event);
      expect(conclusion).toBe("failure");
      expect(failures.map((f) => f.code)).toEqual(["CI-GATE-002"]);
      expect(deferred).toEqual([]);
    });
  }

  it("fails closed when the event is not passed at all", () => {
    expect(resolveGate({ integration: skipped }).conclusion).toBe("failure");
  });

  for (const result of ["failure", "cancelled"]) {
    it(`still fails a pull_request run of it that ended ${result} (CI-GATE-001)`, () => {
      const lane = { applicable: true, result };
      const { failures } = resolveGate({ integration: lane }, "pull_request");
      expect(failures.map((f) => f.code)).toEqual(["CI-GATE-001"]);
    });
  }

  it("passes a pull_request run of it that succeeded, with nothing deferred", () => {
    const lane = { applicable: true, result: "success" };
    const { conclusion, deferred } = resolveGate({ integration: lane }, "pull_request");
    expect(conclusion).toBe("success");
    expect(deferred).toEqual([]);
  });

  it("keeps every other lane required on a pull_request", () => {
    const { failures, deferred } = resolveGate({ py: skipped, js: skipped }, "pull_request");
    expect(failures.map((f) => f.code)).toEqual(["CI-GATE-002", "CI-GATE-002"]);
    expect(deferred).toEqual([]);
  });
});

// #5746: a pull request's run is the light job set, draft or not, unless it carries `ci:full`; a
// merge group, a merge train (workflow_dispatch) and a `ci:full` pull request run the heavy lanes.
describe("light-deferred lanes", () => {
  const skipped = { applicable: true, result: "skipped" };
  const reason = "deferred to the merge group";

  it("are the heavy lanes pr.yml runs on a heavy run only, and no other", () => {
    expect([...LIGHT_DEFERRED].sort()).toEqual([
      "a11y",
      "contract",
      "coverage-thresholds",
      "e2e",
      "engine-bench",
      "migrations",
      "rule-roundtrip",
      "security",
    ]);
    expect(LIGHT_DEFERRED_REASON).toBe(reason);
  });

  it("share no lane with the merge-group-only set (integration is gated but deferred there)", () => {
    expect([...LIGHT_DEFERRED].filter((lane) => MERGE_GROUP_ONLY.has(lane))).toEqual([]);
  });

  for (const lane of [...LIGHT_DEFERRED].sort()) {
    it(`reads a skipped ${lane} on a pull_request without ci:full as deferred, not CI-GATE-002`, () => {
      expect(evaluateLane(lane, skipped, "pull_request", false, true)).toEqual({
        ok: true,
        code: null,
        reason: null,
        deferred: reason,
      });
      const { conclusion, failures, deferred } = resolveGate(
        { [lane]: skipped },
        "pull_request",
        false,
        false,
        true,
      );
      expect(conclusion).toBe("success");
      expect(failures).toEqual([]);
      expect(deferred).toEqual([{ lane, reason }]);
    });

    it(`defers ${lane} on a draft too, whose own CI-GATE-005 still fails it`, () => {
      const { conclusion, failures, deferred } = resolveGate(
        { [lane]: skipped },
        "pull_request",
        true,
        false,
        true,
      );
      expect(conclusion).toBe("failure");
      expect(failures.map((f) => f.code)).toEqual([DRAFT_GATE_CODE]);
      expect(deferred).toEqual([{ lane, reason }]);
    });

    it(`requires ${lane} on a ci:full pull_request (CI-GATE-002)`, () => {
      expect(evaluateLane(lane, skipped, "pull_request", true, true).code).toBe("CI-GATE-002");
      const { conclusion, failures, deferred } = resolveGate(
        { [lane]: skipped },
        "pull_request",
        false,
        true,
        true,
      );
      expect(conclusion).toBe("failure");
      expect(failures.map((f) => f.code)).toEqual(["CI-GATE-002"]);
      expect(deferred).toEqual([]);
    });

    // #5785: the light run defers only while main's merge queue rule is confirmed (MERGE_QUEUE).
    for (const queue of [false, undefined, "true", 1]) {
      it(`fails a light run's skipped ${lane} when the queue flag is ${String(queue)} (CI-GATE-002)`, () => {
        const outcome = evaluateLane(lane, skipped, "pull_request", false, queue);
        expect(outcome).toEqual({
          ok: false,
          code: "CI-GATE-002",
          reason: `gate misconfiguration: ${lane} applicable but skipped; ${NO_QUEUE_REASON}`,
        });
        for (const draft of [false, true]) {
          const { conclusion, failures, deferred } = resolveGate(
            { [lane]: skipped },
            "pull_request",
            draft,
            false,
            queue,
          );
          expect(conclusion).toBe("failure");
          const codes = ["CI-GATE-002", ...(draft ? [DRAFT_GATE_CODE] : [])];
          expect(failures.map((f) => f.code)).toEqual(codes);
          expect(failures[0].reason).toContain("the merge queue on main is not confirmed");
          expect(deferred).toEqual([]);
        }
      });
    }

    for (const event of ["merge_group", "workflow_dispatch", "push", ""]) {
      it(`requires ${lane} on ${event || "an unknown event"} whatever the flags (CI-GATE-002)`, () => {
        for (const [draft, full] of [
          [false, false],
          [true, false],
          [false, true],
          [true, true],
        ]) {
          for (const queue of [false, true]) {
            const { conclusion, failures, deferred } = resolveGate(
              { [lane]: skipped },
              event,
              draft,
              full,
              queue,
            );
            expect(conclusion).toBe("failure");
            expect(failures.map((f) => f.code)).toEqual(["CI-GATE-002"]);
            expect(failures[0].reason).toBe(
              `gate misconfiguration: ${lane} applicable but skipped`,
            );
            expect(deferred).toEqual([]);
          }
        }
      });
    }

    for (const result of ["failure", "cancelled"]) {
      it(`still fails a pull_request run of ${lane} that ended ${result} (CI-GATE-001)`, () => {
        const lanes = { [lane]: { applicable: true, result } };
        expect(resolveGate(lanes, "pull_request").failures.map((f) => f.code)).toEqual([
          "CI-GATE-001",
        ]);
        const { failures } = resolveGate(lanes, "pull_request", true);
        expect(failures.map((f) => f.code)).toEqual(["CI-GATE-001", DRAFT_GATE_CODE]);
      });
    }
  }

  it("passes a light run of a deferred lane that succeeded, with nothing deferred", () => {
    const lane = { applicable: true, result: "success" };
    for (const queue of [false, true]) {
      const { conclusion, deferred } = resolveGate(
        { e2e: lane },
        "pull_request",
        false,
        false,
        queue,
      );
      expect(conclusion).toBe("success");
      expect(deferred).toEqual([]);
    }
  });

  it("keeps a light-set lane required on a pull_request without ci:full (CI-GATE-002)", () => {
    const { conclusion, failures, deferred } = resolveGate(
      { js: skipped, py: skipped },
      "pull_request",
    );
    expect(conclusion).toBe("failure");
    expect(failures.map((f) => f.code)).toEqual(["CI-GATE-002", "CI-GATE-002"]);
    expect(deferred).toEqual([]);
  });

  it("counts only the boolean true as the ci:full flag", () => {
    const result = resolveGate({ e2e: skipped }, "pull_request", false, "true", true);
    expect(result.conclusion).toBe("success");
  });

  it("fails closed when the queue flag is not passed at all", () => {
    const { conclusion, failures } = resolveGate({ e2e: skipped }, "pull_request");
    expect(conclusion).toBe("failure");
    expect(failures.map((f) => f.code)).toEqual(["CI-GATE-002"]);
  });

  it("reports the merge-group reasons for integration and e2e on one light run", () => {
    const { conclusion, failures, deferred } = resolveGate(
      { integration: skipped, e2e: skipped },
      "pull_request",
      false,
      false,
      true,
    );
    expect(conclusion).toBe("success");
    expect(failures).toEqual([]);
    expect(deferred).toEqual([
      { lane: "integration", reason: "runs on the merge group" },
      { lane: "e2e", reason },
    ]);
  });
});

// #5746, the issue's test plan: every changed-paths filter output, on each of the four events,
// draft or not, labelled ci:full or not. The jobs pr.yml runs are modelled here (a heavy lane runs
// when its filter is true on a heavy run; a light-set lane whenever its filter is true), every lane
// that runs is green, and the conclusion and the deferred lanes are what the gate semantics say.
describe("filter outputs x events x draft x ci:full x merge queue", () => {
  // Lane -> the filter outputs it is applicable on (pr.yml's `ci-required` lane table).
  const lanes = {
    js: ["js"],
    py: ["py"],
    architecture: ["py"],
    "pin-check": ["infra"],
    "rule-roundtrip": ["rules"],
    contract: ["protocol"],
    integration: ["py"],
    migrations: ["migrations"],
    security: ["js", "py", "infra", "semgrep"],
    e2e: ["e2e"],
    a11y: ["e2e"],
    "engine-bench": ["engine", "protocol"],
    "coverage-thresholds": ["js", "py"],
  };
  const filters = ["js", "py", "engine", "protocol", "infra", "image", "docs", "e2e"];
  filters.push("migrations", "rules", "semgrep");
  const events = ["pull_request", "merge_group", "workflow_dispatch", ""];

  for (const filter of filters) {
    for (const event of events) {
      for (const draft of [false, true]) {
        for (const full of [false, true]) {
          for (const queue of [true, false]) {
            const heavy = event !== "pull_request" || full;
            const name = `${filter} on ${event || "an unknown event"}, draft ${draft}, ci:full ${full}, queue ${queue}`;
            it(name, () => {
              const input = {};
              const expectDeferred = [];
              for (const [lane, on] of Object.entries(lanes)) {
                const applicable = on.includes(filter);
                const ranHere =
                  lane === "integration"
                    ? event !== "pull_request" && heavy
                    : heavy || !LIGHT_DEFERRED.has(lane);
                input[lane] = { applicable, result: applicable && ranHere ? "success" : "skipped" };
                if (applicable && !ranHere) {
                  expectDeferred.push({
                    lane,
                    reason:
                      lane === "integration"
                        ? "runs on the merge group"
                        : "deferred to the merge group",
                  });
                }
              }
              const { conclusion, failures, deferred } = resolveGate(
                input,
                event,
                draft,
                full,
                queue,
              );
              const draftGate = event === "pull_request" && draft;
              // #5785: without the queue a light run defers nothing: each skipped heavy lane fails.
              const unqueued = queue ? [] : expectDeferred.filter((d) => d.lane !== "integration");
              const codes = [
                ...unqueued.map(() => "CI-GATE-002"),
                ...(draftGate ? [DRAFT_GATE_CODE] : []),
              ];
              expect(failures.map((f) => f.code)).toEqual(codes);
              expect(conclusion).toBe(codes.length > 0 ? "failure" : "success");
              expect(deferred).toEqual(
                queue ? expectDeferred : expectDeferred.filter((d) => d.lane === "integration"),
              );
            });
          }
        }
      }
    }
  }
});

// E03-T14 (Gherkin S1): a diff outside the engine and protocol filters skips engine-bench; the
// resolver names that as not applicable and the conclusion stays success.
describe("not-applicable reporting", () => {
  const off = { applicable: false, result: "skipped" };

  it("names only engine-bench", () => {
    expect([...REPORT_NA]).toEqual(["engine-bench"]);
  });

  it("reports a skipped engine-bench that does not apply, with a success conclusion", () => {
    const { conclusion, failures, notApplicable } = resolveGate({ "engine-bench": off, js: off });
    expect(conclusion).toBe("success");
    expect(failures).toEqual([]);
    expect(notApplicable).toEqual([
      { lane: "engine-bench", reason: "no engine or protocol path changed" },
    ]);
  });

  it("reports nothing when engine-bench applies and passed", () => {
    const lane = { applicable: true, result: "success" };
    expect(resolveGate({ "engine-bench": lane }).notApplicable).toEqual([]);
  });

  it("does not name other lanes that do not apply", () => {
    expect(resolveGate({ e2e: off, py: off }).notApplicable).toEqual([]);
  });

  it("still fails an applicable engine-bench that was skipped", () => {
    const { conclusion, notApplicable } = resolveGate({
      "engine-bench": { applicable: true, result: "skipped" },
    });
    expect(conclusion).toBe("failure");
    expect(notApplicable).toEqual([]);
  });
});

// A draft pull request never passes ci-required (CI-GATE-005, #5506).
describe("draft gate (CI-GATE-005)", () => {
  const green = { js: { applicable: true, result: "success" } };

  it("fails a draft pull_request whose every lane is green", () => {
    const { conclusion, failures } = resolveGate(green, "pull_request", true);
    expect(conclusion).toBe("failure");
    expect(failures).toEqual([{ ok: false, code: "CI-GATE-005", reason: DRAFT_GATE_REASON }]);
    expect(DRAFT_GATE_REASON).toBe(
      "draft pull request: ci-required passes once it is ready for review",
    );
  });

  it("passes a ready pull_request with the same lanes", () => {
    expect(resolveGate(green, "pull_request", false).conclusion).toBe("success");
    expect(resolveGate(green, "pull_request").conclusion).toBe("success");
  });

  it("fails a ci:full draft too: the label runs the heavy lanes, not the gate", () => {
    const { failures } = resolveGate(green, "pull_request", true, true);
    expect(failures.map((f) => f.code)).toEqual([DRAFT_GATE_CODE]);
  });

  for (const event of ["merge_group", "workflow_dispatch", "push", ""]) {
    it(`is unaffected on ${event || "an unknown event"} even with the flag set`, () => {
      const { conclusion, failures } = resolveGate(green, event, true);
      expect(conclusion).toBe("success");
      expect(failures).toEqual([]);
    });
  }

  it("counts only the boolean true as a draft", () => {
    expect(resolveGate(green, "pull_request", "true").conclusion).toBe("success");
  });
});

// The CLI entry point runs from wherever the resolver file is, whatever its path is spelt as.
describe("CLI entry point", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const source = resolve(here, "../../../scripts/ci_gate_resolver.mjs");
  const root = mkdtempSync(join(tmpdir(), "ci gate resolver "));
  afterAll(() => rmSync(root, { recursive: true, force: true }));
  const spaced = join(root, "a dir with spaces", "ci_gate_resolver.mjs");
  mkdirSync(dirname(spaced));
  copyFileSync(source, spaced);
  const linked = join(root, "linked dir");
  symlinkSync(dirname(spaced), linked);
  const run = (script, lanes) =>
    spawnSync(process.execPath, [script, JSON.stringify(lanes)], {
      encoding: "utf8",
      env: { PATH: process.env.PATH, GITHUB_EVENT_NAME: "pull_request" },
    });
  const green = { js: { applicable: true, result: "success" } };
  const red = { js: { applicable: true, result: "failure" } };

  for (const [label, script] of [
    ["the repository path", source],
    ["a path with spaces", spaced],
    ["a symlinked path", join(linked, "ci_gate_resolver.mjs")],
  ]) {
    it(`evaluates the lanes when run from ${label}`, () => {
      const pass = run(script, green);
      expect(pass.status).toBe(0);
      expect(pass.stdout).toContain("ci-required conclusion: success");
      const fail = run(script, red);
      expect(fail.status).toBe(1);
      expect(fail.stdout).toContain("ci-required conclusion: failure");
      expect(fail.stderr).toContain("CI-GATE-001: js required and not successful");
    });
  }

  it("does not run when imported (no argv entry of its own)", () => {
    const probe = spawnSync(
      process.execPath,
      [
        "--input-type=module",
        "-e",
        `await import(${JSON.stringify(pathToFileURL(spaced).href)}); console.log("ok")`,
      ],
      { encoding: "utf8" },
    );
    expect(probe.status).toBe(0);
    expect(probe.stdout.trim()).toBe("ok");
  });
});
