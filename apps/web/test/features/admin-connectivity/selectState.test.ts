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

// E08-D09 §5.2 "Token tone" column, row for row, typed here from the spec (not from states.ts).
const D09_TONES: Readonly<Record<string, string>> = {
  "S-01": "color.status.success.strong",
  "S-02": "color.status.warning.strong",
  "S-03": "color.status.warning.strong",
  "S-04": "color.status.danger.strong",
  "S-05": "color.status.danger.strong",
  "S-06": "color.data-confidence.disconnected.*",
  "S-07": "color.data-confidence.reconnecting.*",
  "S-08": "color.status.warning.strong",
  "S-09": "color.status.warning.strong",
  "S-10": "color.status.danger.strong",
  "S-11": "color.status.danger.strong",
  "S-12": "color.status.warning.strong",
  "S-13": "CMP-015",
  "S-14": "color.neutral.default",
  "S-15": "color.data-confidence.stale.*",
  "S-16": "color.status.warning.strong",
  "S-17": "color.status.danger.strong",
  "S-18": "color.status.danger.strong",
  "S-19": "color.neutral.default",
  "S-20": "color.status.warning.strong",
};

describe("the register tones (E08-D09 §5.2, §16 RULED BQ-19)", () => {
  it.each(STATE_IDS)("%s carries the tone D09 names", (id) => {
    expect(toneOf(id)).toBe(D09_TONES[id]);
  });

  it("covers every state and never gives a rate or clock state a data-confidence token", () => {
    expect(Object.keys(D09_TONES)).toEqual([...STATE_IDS]);
    const rateAndClock = ["S-02", "S-03", "S-04", "S-05", "S-08", "S-09", "S-10", "S-11", "S-12"];
    for (const id of rateAndClock) expect(toneOf(id as "S-02")).toMatch(/^color\.status\./);
  });
});

describe("the 900 s clock limit (D09 :271)", () => {
  it("keeps a clock row off S-15 between its measurements", () => {
    const clock = { asOfIsClock: true, clockOffsetMs: 0 };
    expect(pick({ ...clock, asOfAgeMs: 5 * 60_000 })).not.toBe("S-15");
    expect(pick({ ...clock, asOfAgeMs: THRESHOLDS.clockStaleAfterMs })).not.toBe("S-15");
    expect(pick({ ...clock, asOfAgeMs: THRESHOLDS.clockStaleAfterMs + 1 })).toBe("S-15");
    expect(THRESHOLDS.clockStaleAfterMs).toBe(900_000);
  });

  it("still reads a value row stale after 5 s", () => {
    expect(pick({ asOfAgeMs: THRESHOLDS.staleAfterMs + 1 })).toBe("S-15");
  });
});

describe("the register", () => {
  it("gives every state a word; S-06 alone is assertive", () => {
    for (const id of STATE_IDS) {
      expect(wordOf(id).length).toBeGreaterThan(0);
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
