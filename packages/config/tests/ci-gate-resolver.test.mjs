import { describe, expect, it } from "vitest";
import {
  DRAFT_DEFERRED,
  evaluateLane,
  MERGE_GROUP_ONLY,
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
    const { failures, deferred } = resolveGate(
      { py: skipped, migrations: skipped },
      "pull_request",
    );
    expect(failures.map((f) => f.code)).toEqual(["CI-GATE-002", "CI-GATE-002"]);
    expect(deferred).toEqual([]);
  });
});

// The e2e, a11y and engine-bench jobs skip a pull request while it is a draft; the run that
// ready_for_review starts, and every merge-group run, executes them.
describe("draft-deferred lanes", () => {
  const skipped = { applicable: true, result: "skipped" };
  const reason = "runs when the pull request leaves draft";

  it("are e2e, a11y and engine-bench and no other", () => {
    expect([...DRAFT_DEFERRED].sort()).toEqual(["a11y", "e2e", "engine-bench"]);
  });

  it("share no lane with the merge-group-only set", () => {
    expect([...DRAFT_DEFERRED].filter((lane) => MERGE_GROUP_ONLY.has(lane))).toEqual([]);
  });

  for (const lane of [...DRAFT_DEFERRED].sort()) {
    it(`reads a skipped ${lane} lane on a draft pull_request as deferred, not as CI-GATE-002`, () => {
      expect(evaluateLane(lane, skipped, "pull_request", true)).toEqual({
        ok: true,
        code: null,
        reason: null,
        deferred: reason,
      });
      const { conclusion, failures, deferred } = resolveGate(
        { [lane]: skipped },
        "pull_request",
        true,
      );
      expect(conclusion).toBe("success");
      expect(failures).toEqual([]);
      expect(deferred).toEqual([{ lane, reason }]);
    });

    it(`still requires ${lane} on a pull_request that is not a draft (CI-GATE-002)`, () => {
      const { conclusion, failures, deferred } = resolveGate({ [lane]: skipped }, "pull_request");
      expect(conclusion).toBe("failure");
      expect(failures.map((f) => f.code)).toEqual(["CI-GATE-002"]);
      expect(deferred).toEqual([]);
      expect(resolveGate({ [lane]: skipped }, "pull_request", false).conclusion).toBe("failure");
    });

    for (const event of ["merge_group", "workflow_dispatch", "push", ""]) {
      it(`ignores the draft flag on ${event || "an unknown event"}: ${lane} required (CI-GATE-002)`, () => {
        const { conclusion, failures, deferred } = resolveGate({ [lane]: skipped }, event, true);
        expect(conclusion).toBe("failure");
        expect(failures.map((f) => f.code)).toEqual(["CI-GATE-002"]);
        expect(deferred).toEqual([]);
      });
    }

    for (const result of ["failure", "cancelled"]) {
      it(`still fails a draft's run of ${lane} that ended ${result} (CI-GATE-001)`, () => {
        const lanes = { [lane]: { applicable: true, result } };
        const { failures } = resolveGate(lanes, "pull_request", true);
        expect(failures.map((f) => f.code)).toEqual(["CI-GATE-001"]);
      });
    }
  }

  it("passes a draft's run of a deferred lane that succeeded, with nothing deferred", () => {
    const lane = { applicable: true, result: "success" };
    const { conclusion, deferred } = resolveGate({ e2e: lane }, "pull_request", true);
    expect(conclusion).toBe("success");
    expect(deferred).toEqual([]);
  });

  it("keeps a non-deferred lane required on a draft pull_request (CI-GATE-002)", () => {
    const { conclusion, failures, deferred } = resolveGate(
      { js: skipped, py: skipped },
      "pull_request",
      true,
    );
    expect(conclusion).toBe("failure");
    expect(failures.map((f) => f.code)).toEqual(["CI-GATE-002", "CI-GATE-002"]);
    expect(deferred).toEqual([]);
  });

  it("reports the merge-group reason for integration and the draft reason for e2e on one draft", () => {
    const { conclusion, deferred } = resolveGate(
      { integration: skipped, e2e: skipped },
      "pull_request",
      true,
    );
    expect(conclusion).toBe("success");
    expect(deferred).toEqual([
      { lane: "integration", reason: "runs on the merge group" },
      { lane: "e2e", reason },
    ]);
  });
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
