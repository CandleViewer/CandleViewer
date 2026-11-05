// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  flagPushes,
  inOrder,
  listedFlag,
  noticePushes,
  pushedKeys,
  recordToFrameMs,
  rowsOf,
  runUndos,
  stepUpTrail,
  systemDeltas,
  writeAheadRecord,
  writtenVersion,
} from "../e2e/admin/flagFrames";

/**
 * E42-Q02 (#1215) part 2: the readings admin-flags.stack.ts takes from a tapped socket, the flag
 * list and the audit slice, on synthetic frames and rows: a slip here would let the real lane pass
 * on the wrong frame or the wrong record, which no real run would show.
 */
const delta = (ts: number, p: unknown) => ({ t: "d", ch: "system", s: 2, ts, e: "j", p });
const flags = (ts: number, set: Record<string, unknown>) =>
  delta(ts, { kind: "feature_flags", feature_flags: set });
const notice = (ts: number, reason: string, extra: Record<string, unknown> = {}) =>
  delta(ts, { kind: "notice", severity: "warning", message: "m", reason, ...extra });

describe("the system pushes a socket got", () => {
  it("reads only system deltas with a numeric ts, from the index given on", () => {
    const frames = [
      flags(1, { a: true }),
      { t: "snap", ch: "system", s: 1, ts: 2, p: { kind: "feature_flags" } },
      { t: "d", ch: "orders", s: 1, ts: 3, p: { kind: "feature_flags" } },
      { t: "d", ch: "system", ts: "4", p: { kind: "notice" } },
      { t: "d", ch: "system", ts: 5, p: [] },
      { t: "d", ch: "system", ts: Number.NaN, p: { kind: "notice" } },
      flags(7, { b: false }),
    ];
    expect(systemDeltas(frames).map((d) => d.ts)).toEqual([1, 7]);
    expect(systemDeltas(frames, 1).map((d) => d.ts)).toEqual([7]);
  });

  it("gives each push of one key in order, its value and its ts, a falsy value included", () => {
    const frames = [
      flags(1, { a: true }),
      flags(2, { b: true }),
      notice(3, "x"),
      flags(4, { a: false }),
      delta(5, { kind: "health", feature_flags: { a: true } }),
    ];
    expect(flagPushes(frames, "a")).toEqual([
      { ts: 1, value: true },
      { ts: 4, value: false },
    ]);
    expect(flagPushes(frames, "a", 1)).toEqual([{ ts: 4, value: false }]);
    expect(flagPushes(frames, "toString")).toEqual([]); // own keys only
  });

  it("names every key a feature_flags push carried, once each and sorted", () => {
    const frames = [flags(1, { z: 1 }), flags(2, { a: 1, z: 2 }), notice(3, "x")];
    expect(pushedKeys(frames)).toEqual(["a", "z"]);
    expect(pushedKeys(frames, 3)).toEqual([]);
  });

  it("gives the notices of one reason with the members their body carries", () => {
    const frames = [
      notice(1, "maintenance.enabled"),
      notice(2, "maintenance.disabled", { severity: "info" }),
      notice(3, "maintenance.enabled", { engaged_by: "u" }),
    ];
    expect(noticePushes(frames, "maintenance.enabled")).toEqual([
      { ts: 1, severity: "warning", members: ["kind", "message", "reason", "severity"] },
      {
        ts: 3,
        severity: "warning",
        members: ["engaged_by", "kind", "message", "reason", "severity"],
      },
    ]);
    expect(noticePushes(frames, "maintenance.disabled").map((n) => n.severity)).toEqual(["info"]);
  });
});

describe("the flag list and a write's answer", () => {
  const body = {
    resolution: "stored",
    items: [
      { key: "a", value: true, updated_at: "2026-11-05T10:00:00.000001Z" },
      { key: "b", value: false },
    ],
  };

  it("reads a flag's value and the version a write names", () => {
    expect(listedFlag(body, "a")).toEqual({
      value: true,
      updatedAt: "2026-11-05T10:00:00.000001Z",
    });
  });

  it.each([
    ["missing", body, "c"],
    ["unversioned (a fail-closed answer)", body, "b"],
    ["in a body with no list", { resolution: "fail_closed" }, "a"],
    ["in no body", null, "a"],
  ])("refuses a flag that is %s", (_named, given, key) => {
    expect(() => listedFlag(given, key)).toThrow(/the flag list has no versioned/u);
  });

  it("takes the next version from a write's answer, and refuses an answer without one", () => {
    expect(writtenVersion({ key: "a", updated_at: "v2" })).toBe("v2");
    expect(() => writtenVersion({ key: "a" })).toThrow(/answered no updated_at/u);
    expect(() => writtenVersion(null)).toThrow(/answered no updated_at/u);
  });
});

describe("the audit records a write left", () => {
  const row = (action: string, requestId: string, outcome: string, at: string, reason = "r") => ({
    action,
    request_id: requestId,
    outcome,
    event_ts: at,
    reason,
  });
  const rows = [
    row("flags.change", "q1", "failure", "2026-11-05T10:00:00.000Z", "kind_mismatch"),
    row("flags.change", "q2", "success", "2026-11-05T10:00:01.000Z"),
    row("flags.change", "q2", "success", "2026-11-05T10:00:01.050Z", "ok"),
    row("auth.step_up_required", "q2", "denied", "2026-11-05T10:00:00.500Z", "flags"),
  ];

  it("reads one request's rows of one action, in the slice's order", () => {
    expect(rowsOf(rows, "flags.change", "q2").map((r) => r["reason"])).toEqual(["r", "ok"]);
    expect(rowsOf(rows, "flags.change", "q3")).toEqual([]);
  });

  it("takes the first successful flags.change as the write-ahead record, never a refusal", () => {
    expect(writeAheadRecord(rows, "q2")?.["reason"]).toBe("r");
    expect(writeAheadRecord(rows, "q1")).toBeUndefined();
  });

  it("measures from a record's event_ts to a frame's ts, microseconds and offsets read", () => {
    const at = { event_ts: "2026-11-05T10:00:01.250123+00:00" };
    expect(recordToFrameMs(at, Date.parse("2026-11-05T10:00:02.000Z"))).toBe(750);
    expect(recordToFrameMs(at, Date.parse("2026-11-05T10:00:01.000Z"))).toBe(-250);
  });

  it.each([
    ["no event_ts", {}, 1],
    ["an unreadable event_ts", { event_ts: "soon" }, 1],
    ["a frame without a ts", { event_ts: "2026-11-05T10:00:00Z" }, Number.NaN],
  ])("refuses to measure with %s", (_named, given, ts) => {
    expect(() => recordToFrameMs(given, ts)).toThrow(/readable event_ts/u);
  });

  it("lists the step-up records as action and class, and nothing else", () => {
    expect(stepUpTrail(rows)).toEqual(["auth.step_up_required:flags"]);
    expect(stepUpTrail([{ action: "auth.step_up_granted", reason: null }])).toEqual([
      "auth.step_up_granted:null",
    ]);
  });

  it("finds entries in order with others between, and never out of order", () => {
    const trail = ["a", "x", "b", "a", "c"];
    expect(inOrder(trail, ["a", "b", "c"])).toBe(true);
    expect(inOrder(trail, [])).toBe(true);
    expect(inOrder(trail, ["b", "a", "c"])).toBe(true);
    expect(inOrder(trail, ["c", "a"])).toBe(false);
    expect(inOrder(trail, ["a", "a", "a"])).toBe(false);
    expect(inOrder([], ["a"])).toBe(false);
  });
});

describe("the undo stack a test leaves its flags on", () => {
  it("runs the newest step first and leaves the stack empty", async () => {
    const ran: string[] = [];
    const stack = ["a", "b", "c"].map((label) => ({
      label,
      run: async () => {
        ran.push(label);
      },
    }));
    expect(await runUndos(stack)).toEqual([]);
    expect(ran).toEqual(["c", "b", "a"]);
    expect(stack).toEqual([]);
  });

  it("reports a failing step by label and still runs the older ones", async () => {
    const ran: string[] = [];
    const stack = [
      { label: "old", run: async () => void ran.push("old") },
      {
        label: "bad",
        run: async () => {
          throw new Error("answered 500");
        },
      },
    ];
    expect(await runUndos(stack)).toEqual(["bad: answered 500"]);
    expect(ran).toEqual(["old"]);
  });

  it("is a no-op on an empty stack", async () => {
    expect(await runUndos([])).toEqual([]);
  });
});
