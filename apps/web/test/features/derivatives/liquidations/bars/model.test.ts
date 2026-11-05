// E24-S06 (#781) slice 1: the bars' model. The story's trap first: a bar with no recorded data is unknown, never zero,
// and the boundary comes from `first_available_ts`, not from the first non-empty bucket.
import { describe, expect, it } from "vitest";
import type { LiqCoverage } from "../../../../../src/features/derivatives/liquidations/history";
import {
  asNotional,
  barAt,
  barState,
  barWindow,
  boundaryOf,
  buildBars,
  gridDifference,
  MAX_WINDOW_BARS,
  MAX_WINDOW_DAYS,
  recordedPosition,
  TIME_PARAMS,
} from "../../../../../src/features/derivatives/liquidations/bars/model";
import {
  COVERAGE,
  DAY_COVERAGE,
  DAY_LONG,
  DAY_SHORT,
  FIRST,
  HOUR,
  NOW,
  SERVED_LONG,
  SERVED_SHORT,
} from "../../../../../src/features/derivatives/liquidations/bars/samples";

const at = (hh: number, day = "2026-10-21"): number =>
  Date.parse(`${day}T${String(hh).padStart(2, "0")}:00:00Z`);

describe("zero versus unknown (sc. 5)", () => {
  it("reads the served 0 before the recorder began as unknown, never zero", () => {
    const bars = buildBars(SERVED_LONG, SERVED_SHORT, COVERAGE, HOUR);
    expect(bars.map((b) => [b.tMs, b.state])).toEqual([
      [at(7), "unknown"],
      [at(8), "unknown"],
      [at(9), "unknown"], // straddles 09:14, reads 0: only part of the bar was recorded
      [at(10), "zero"],
      [at(11), "recorded"],
    ]);
    expect(bars[0]).toMatchObject({ long: null, short: null });
  });

  it("keeps a genuine zero a zero, with its figures", () => {
    expect(barState(at(10), HOUR, COVERAGE, "0", "0.00")).toEqual({
      tMs: at(10),
      state: "zero",
      long: "0",
      short: "0.00",
      partialFromMs: null,
    });
  });

  it("is recorded when one side is zero beside a positive one", () => {
    expect(barState(at(10), HOUR, COVERAGE, "0", "12.5").state).toBe("recorded");
  });

  it("keeps the recorded part of a bar that straddles the first print, marked from when it was recorded", () => {
    expect(barState(at(9), HOUR, COVERAGE, "10", "0")).toMatchObject({
      state: "recorded",
      partialFromMs: FIRST,
    });
    expect(barState(at(10), HOUR, COVERAGE, "10", "0").partialFromMs).toBeNull();
  });

  it("is unknown for a value the server did not send, on either side", () => {
    expect(barState(at(11), HOUR, COVERAGE, null, "5").state).toBe("unknown");
    expect(barState(at(11), HOUR, COVERAGE, "5", null).state).toBe("unknown");
  });

  it("is unknown for every bar when nothing is stored or the first print is after the bar, however it reads", () => {
    const never: LiqCoverage = { ...COVERAGE, firstAvailableMs: null, noCoverage: true };
    expect(barState(at(11), HOUR, never, "9", "9").state).toBe("unknown");
    const later: LiqCoverage = { ...COVERAGE, firstAvailableMs: NOW + HOUR };
    expect(barState(at(11), HOUR, later, "9", "9").state).toBe("unknown");
    expect(recordedPosition(at(11), HOUR, never)).toBe("outside");
  });

  it("places a bar that closes exactly at the first print outside, and one that opens at it inside", () => {
    const edge: LiqCoverage = { ...COVERAGE, firstAvailableMs: at(10) };
    expect(recordedPosition(at(9), HOUR, edge)).toBe("outside");
    expect(recordedPosition(at(10), HOUR, edge)).toBe("inside");
  });

  it("builds one bar per t either side served; a side that omits a t makes it unknown", () => {
    const bars = buildBars(new Map([[at(11), "1"]]), new Map([[at(10), "2"]]), COVERAGE, HOUR);
    expect(bars.map((b) => [b.tMs, b.state])).toEqual([
      [at(10), "unknown"],
      [at(11), "unknown"],
    ]);
  });

  it("accepts only exact non-negative decimal strings", () => {
    expect(["0", "12.50", "1e5", "-1", 5, null, " 1", "1."].map(asNotional)).toEqual([
      "0",
      "12.50",
      null,
      null,
      null,
      null,
      null,
      null,
    ]);
  });
});

describe("the boundary (sc. 4)", () => {
  const WINDOW = { from: at(7), to: NOW };
  it("is the coverage's first available time, in view when it falls inside the window", () => {
    expect(boundaryOf(COVERAGE, WINDOW.from, WINDOW.to)).toEqual({ kind: "in-view", atMs: FIRST });
  });

  it("does not follow the first non-empty bucket", () => {
    // the first recorded print is far later than `first_available_ts`: the label still reads the coverage
    const bars = buildBars(SERVED_LONG, SERVED_SHORT, COVERAGE, HOUR);
    const firstNonZero = bars.find((b) => b.state === "recorded")?.tMs;
    const b = boundaryOf(COVERAGE, WINDOW.from, WINDOW.to);
    expect(b.kind === "in-view" && b.atMs).toBe(FIRST);
    expect(b.kind === "in-view" && b.atMs).not.toBe(firstNonZero);
  });

  it("is none when the window starts at or after the first stored print", () => {
    expect(boundaryOf(DAY_COVERAGE, at(22, "2026-10-20"), NOW)).toEqual({ kind: "none" });
    expect(
      boundaryOf({ ...COVERAGE, firstAvailableMs: WINDOW.from }, WINDOW.from, WINDOW.to),
    ).toEqual({
      kind: "none",
    });
  });

  it("is before when the whole window precedes the first print, never when nothing is stored", () => {
    // `first_available_ts` alone decides: a `no_coverage` flag beside a first print inside the window is a marker
    expect(boundaryOf({ ...COVERAGE, noCoverage: true }, WINDOW.from, WINDOW.to).kind).toBe(
      "in-view",
    );
    expect(
      boundaryOf({ ...COVERAGE, firstAvailableMs: WINDOW.to }, WINDOW.from, WINDOW.to).kind,
    ).toBe("before");
    expect(
      boundaryOf({ ...COVERAGE, firstAvailableMs: NOW + 1 }, WINDOW.from, WINDOW.to).kind,
    ).toBe("before");
    expect(
      boundaryOf(
        { firstAvailableMs: null, coveredFromMs: null, coveredToMs: null, noCoverage: true },
        WINDOW.from,
        WINDOW.to,
      ),
    ).toEqual({ kind: "never" });
  });
});

describe("the bar grid (sc. 2)", () => {
  const priceTimes = [22, 23].map((h) => at(h, "2026-10-20")).concat([0, 1, 2].map((h) => at(h)));
  it("is the price chart's own across a UTC day boundary: no bar missing, none extra", () => {
    const bars = buildBars(DAY_LONG, DAY_SHORT, DAY_COVERAGE, HOUR);
    expect(bars.map((b) => b.tMs)).toEqual(priceTimes);
    expect(gridDifference(bars, priceTimes)).toEqual({ missing: [], extra: [] });
    expect(bars.map((b) => new Date(b.tMs).getUTCHours())).toEqual([22, 23, 0, 1, 2]);
  });

  it("reports a difference rather than re-bucketing it", () => {
    const bars = buildBars(DAY_LONG, DAY_SHORT, DAY_COVERAGE, HOUR);
    const shifted = priceTimes.map((t) => t + 30 * 60_000);
    const d = gridDifference(bars, shifted);
    expect(d.missing).toEqual(shifted);
    expect(d.extra).toEqual(priceTimes);
  });

  it("finds the bar under the crosshair by its span", () => {
    const bars = buildBars(DAY_LONG, DAY_SHORT, DAY_COVERAGE, HOUR);
    expect(barAt(bars, at(0) + 59 * 60_000, HOUR)?.tMs).toBe(at(0));
    expect(barAt(bars, at(3), HOUR)).toBeNull();
  });
});

describe("the history bound", () => {
  it("is the default 500 bars, aligned to the grid", () => {
    const w = barWindow(NOW, HOUR);
    expect(w.bars).toBe(500);
    expect(w.toMs).toBe(NOW);
    expect(w.fromMs).toBe(at(11) - 499 * HOUR);
  });

  it("never asks for more than 1,500 bars", () => {
    expect(barWindow(NOW, TIME_PARAMS["1"] ?? 0, 5_000).bars).toBe(MAX_WINDOW_BARS);
  });

  it("never asks for more than 400 days: a weekly chart holds 57 bars, a daily one 400", () => {
    expect(barWindow(NOW, TIME_PARAMS["W"] ?? 0, 1_000).bars).toBe(57);
    const d = barWindow(NOW, TIME_PARAMS["D"] ?? 0, 1_000);
    expect(d.bars).toBe(MAX_WINDOW_DAYS);
    expect(NOW - d.fromMs).toBeLessThanOrEqual(MAX_WINDOW_DAYS * 86_400_000);
  });

  it("knows the server's time interval codes", () => {
    expect(Object.keys(TIME_PARAMS)).toEqual([
      "1",
      "3",
      "5",
      "15",
      "30",
      "60",
      "120",
      "240",
      "360",
      "720",
      "D",
      "W",
    ]);
    expect(TIME_PARAMS["60"]).toBe(HOUR);
  });
});
