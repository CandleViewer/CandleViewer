import { describe, expect, it } from "vitest";
import {
  PRECEDENCE,
  THRESHOLDS,
  activeStates,
  selectConnectivityState,
  type StateSignals,
} from "../../../src/features/admin-connectivity/selectState";
import { STATE_IDS, STATES, toneOf, wordOf } from "../../../src/features/admin-connectivity/states";

const ON: StateSignals = { enabled: true, read: "ok", usedPctOfSpendable: 10 };
const pick = (extra: Partial<StateSignals>): ReturnType<typeof selectConnectivityState> =>
  selectConnectivityState({ ...ON, ...extra });

describe("the state selector: one id per trigger (E08-D13 §5.4)", () => {
  const cases: ReadonlyArray<readonly [string, Partial<StateSignals>]> = [
    ["S-01", {}],
    ["S-02", { usedPctOfSpendable: THRESHOLDS.nearLimitPct }],
    ["S-03", { throttled: true }],
    ["S-04", { ipHold: true }],
    ["S-05", { banned: true }],
    ["S-06", { connection: "disconnected" }],
    ["S-07", { connection: "reconnecting" }],
    ["S-08", { resubscribesInWindow: THRESHOLDS.resubscribeStormCount + 1 }],
    ["S-09", { clockOffsetMs: THRESHOLDS.clockWarnMs + 1 }],
    ["S-10", { clockOffsetMs: -(THRESHOLDS.clockHaltMs + 1) }],
    ["S-11", { refused10002: true }],
    ["S-12", { clockOffsetMs: null }],
    ["S-13", { read: "loading" }],
    ["S-14", { inspectorTopics: 0 }],
    ["S-15", { asOfAgeMs: THRESHOLDS.staleAfterMs + 1 }],
    ["S-16", { errorSlices: 1, okSlices: 1 }],
    ["S-17", { read: "error" }],
    ["S-18", { read: "failed" }],
    ["S-19", { read: "unavailable" }],
    ["S-20", { dropped: true }],
  ];
  it.each(cases)("%s", (id, extra) => expect(pick(extra)).toBe(id));

  it("covers all twenty states", () => {
    expect(cases.map(([id]) => id).sort()).toEqual([...STATE_IDS].sort());
  });

  it("reads S-19 when the slice flag is off, whatever else is true", () => {
    expect(selectConnectivityState({ ...ON, enabled: false, banned: true })).toBe("S-19");
  });

  it("never reads S-01 without a served spendable share (no calm default)", () => {
    expect(selectConnectivityState({ enabled: true, read: "ok" })).toBe("S-19");
    expect(selectConnectivityState({ enabled: true, read: "none" })).toBe("S-19");
  });

  it("keeps the thresholds' edges: 80 % enters, 500 ms and 2 000 ms are not past", () => {
    expect(pick({ usedPctOfSpendable: 79.9 })).toBe("S-01");
    expect(pick({ clockOffsetMs: THRESHOLDS.clockWarnMs })).toBe("S-01");
    expect(pick({ clockOffsetMs: THRESHOLDS.clockHaltMs })).toBe("S-09");
    expect(pick({ resubscribesInWindow: 1 })).toBe("S-01");
    expect(pick({ asOfAgeMs: THRESHOLDS.staleAfterMs })).toBe("S-01");
  });
});

describe("the precedence table (PROPOSED, E08-D09 §5.2)", () => {
  it("S-05 over S-04 over S-03", () => {
    expect(pick({ banned: true, ipHold: true, throttled: true })).toBe("S-05");
    expect(pick({ ipHold: true, throttled: true })).toBe("S-04");
  });

  it("S-10 over S-09, and the offset's size counts, not its sign", () => {
    expect(activeStates({ ...ON, clockOffsetMs: 3_000 }).has("S-09")).toBe(false);
    expect(pick({ clockOffsetMs: -3_000, connection: "reconnecting" })).toBe("S-10");
  });

  it("lists every state but S-13 (a pre-check) exactly once", () => {
    expect([...PRECEDENCE].sort()).toEqual(STATE_IDS.filter((id) => id !== "S-13").sort());
  });

  it("puts the loading pre-check before the table", () => {
    expect(pick({ read: "loading", banned: true })).toBe("S-13");
  });
});

describe("the register", () => {
  it("gives every state a word and a tone; S-06 alone is assertive", () => {
    for (const id of STATE_IDS) {
      expect(wordOf(id).length).toBeGreaterThan(0);
      expect(["ok", "warning", "danger", "stale", "neutral"]).toContain(toneOf(id));
    }
    expect(STATE_IDS.filter((id) => STATES[id].announce === "assertive")).toEqual(["S-06"]);
  });

  it("gives the three rate states three different words and glyph shapes", () => {
    const words = new Set(["S-03", "S-04", "S-05"].map((id) => wordOf(id as "S-03")));
    expect(words.size).toBe(3);
    expect(new Set([STATES["S-03"].glyph, STATES["S-04"].glyph, STATES["S-05"].glyph]).size).toBe(
      3,
    );
  });
});
