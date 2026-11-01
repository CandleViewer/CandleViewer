/** E08-D06 §7 (CMP-126) and D-7: the funding row's states on a fake clock. */
import { describe, expect, it } from "vitest";
import {
  alarmSkewMs,
  clockText,
  crossedMark,
  fundingState,
  markSentence,
  type FundingInput,
} from "../../../src/features/symbol-info/funding";

const TARGET = Date.parse("2026-11-01T08:00:00Z");
const at = (
  remainingMs: number,
  patch: Partial<FundingInput> = {},
): ReturnType<typeof fundingState> =>
  fundingState({
    symbol: "BTCUSDT",
    trading: true,
    nextFundingMs: TARGET,
    nowMs: TARGET - remainingMs,
    ...patch,
  });

describe("clockText", () => {
  it("floors to a fixed-width hh:mm:ss", () => {
    expect(clockText(5_053_771)).toBe("01:24:13");
    expect(clockText(3_599_999)).toBe("00:59:59");
    expect(clockText(999)).toBe("00:00:00");
    expect(clockText(-5)).toBe("00:00:00");
    expect(clockText(100 * 3_600_000)).toBe("100:00:00");
  });
});

describe("fundingState", () => {
  it("counts down from one hour or more", () => {
    expect(at(5_053_771)).toMatchObject({
      kind: "counting",
      text: "next in 01:24:13 · 08:00 UTC",
      warn: false,
      mark: null,
      spoken: "Next funding in 1 hour 24 minutes, at 08:00 UTC",
    });
  });

  it("keeps the next-in form just under an hour", () => {
    expect(at(3_599_000)).toMatchObject({ text: "next in 00:59:59 · 08:00 UTC", warn: false });
  });

  it("warns and says 'settles in' under 5 minutes, with the 1 minute mark under a minute", () => {
    expect(at(252_000)).toMatchObject({
      kind: "counting",
      text: "settles in 00:04:12 · 08:00 UTC",
      warn: true,
      mark: 5,
    });
    expect(at(59_000)).toMatchObject({ text: "settles in 00:00:59 · 08:00 UTC", mark: 1 });
    expect(at(300_000)).toMatchObject({ warn: false, mark: null });
  });

  it("says the settlement time passed, never negative and never a frozen 00:00:00", () => {
    for (const remaining of [0, -1, -90_000]) {
      expect(at(remaining)).toEqual({
        kind: "passed",
        text: "Settlement time passed — waiting for an update",
        announce: "Settlement time passed — waiting for an update",
      });
    }
    expect(at(1)).toMatchObject({ kind: "counting" });
  });

  it("is suppressed when not trading, with the reason, whatever the time", () => {
    expect(at(10_000, { trading: false })).toEqual({
      kind: "not_trading",
      text: "No funding — BTCUSDT is not trading.",
    });
  });

  it("shows no countdown when the next funding time is absent", () => {
    expect(at(10_000, { nextFundingMs: null })).toEqual({
      kind: "unknown",
      text: "Next funding time not available",
    });
    expect(at(10_000, { nextFundingMs: Number.NaN })).toMatchObject({ kind: "unknown" });
  });

  it("swaps the seconds for the absolute time and a skew note when the clock alarm is on", () => {
    const state = at(5_053_771, {
      alarm: { shellAlarm: false, clientSkewMs: -2_500, exchangeOffsetMs: null },
    });
    expect(state).toEqual({
      kind: "clock_alarm",
      text: "at 08:00:00 UTC (in about 1 h 24 min)",
      note: "Clock skew 2500 ms — the countdown may be off",
      announce: "Clock skew 2500 ms — the countdown may be off",
    });
  });

  it("shows the absolute time alone while the offset is unknown", () => {
    expect(
      at(5_053_771, { alarm: { shellAlarm: true, clientSkewMs: null, exchangeOffsetMs: null } }),
    ).toMatchObject({
      kind: "clock_alarm",
      note: null,
      announce: null,
    });
  });

  it("does not alarm at a client skew of 2 000 ms or less", () => {
    expect(
      at(60_000, { alarm: { shellAlarm: false, clientSkewMs: 2_000, exchangeOffsetMs: 612 } }).kind,
    ).toBe("counting");
    expect(alarmSkewMs({ shellAlarm: true, clientSkewMs: null, exchangeOffsetMs: -612 })).toEqual({
      on: true,
      skewMs: 612,
    });
  });

  it("keeps counting to a fixed target as the clock moves", () => {
    const a = at(90_000);
    const b = at(30_000);
    expect(a).toMatchObject({ text: "settles in 00:01:30 · 08:00 UTC" });
    expect(b).toMatchObject({ text: "settles in 00:00:30 · 08:00 UTC" });
  });
});

describe("crossedMark", () => {
  it("fires 5 min and 1 min once each as the time falls through them", () => {
    expect(crossedMark(310_000, 299_000)).toBe(5);
    expect(crossedMark(299_000, 290_000)).toBeNull();
    expect(crossedMark(61_000, 59_000)).toBe(1);
    expect(crossedMark(59_000, 58_000)).toBeNull();
  });

  it("fires the nearest mark on a first look under a mark, and none at or past the time", () => {
    expect(crossedMark(null, 200_000)).toBe(5);
    expect(crossedMark(null, 30_000)).toBe(1);
    expect(crossedMark(null, 3_600_000)).toBeNull();
    expect(crossedMark(10_000, 0)).toBeNull();
  });

  it("words the announcement", () => {
    expect(markSentence("BTCUSDT", 5)).toBe("BTCUSDT funding settles in 5 minutes.");
    expect(markSentence("BTCUSDT", 1)).toBe("BTCUSDT funding settles in 1 minute.");
  });
});
