// E24-S02 (#777) slice 1: the quadrant lookup, the per-bar model, the pattern floor and the announcement rule.
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  buildOiBars,
  countBars,
  deltaUnitLabel,
} from "../../../src/features/derivatives/oi/quadrant/bars";
import {
  announcement,
  isMaterialChange,
  useUnclassifiedAnnouncement,
} from "../../../src/features/derivatives/oi/quadrant/announce";
import {
  DELTA_SERIES,
  FIXTURE_BAR_MS,
  FIXTURE_ROWS,
  QUADRANT_SERIES,
} from "../../../src/features/derivatives/oi/quadrant/fixture";
import {
  floorRung,
  QUADRANT_ORDER,
  QUADRANT_STYLE,
  NO_QUADRANT_STYLE,
  quadrantOf,
  styleFor,
  quadrantReading,
} from "../../../src/features/derivatives/oi/quadrant/quadrant";
import {
  createOiAnalytics,
  createQuadrantAnalytics,
} from "../../../src/features/derivatives/oi/analytics";

describe("QUADRANT_STYLE", () => {
  it("is keyed by the wire enum and separates the four by position x width before any hue", () => {
    expect(
      QUADRANT_ORDER.map((q) => `${QUADRANT_STYLE[q].side}/${QUADRANT_STYLE[q].width}`),
    ).toEqual(["above/full", "below/full", "above/half", "below/half"]);
    expect(QUADRANT_STYLE.short_covering.prop).toBe("short_cover");
    expect(QUADRANT_STYLE.long_buildup.token).toBe("color.candle.up");
  });

  it("reads the crosshair form in words", () => {
    expect(quadrantReading("long_buildup")).toBe("long build-up (▲ price ▲ OI)");
    expect(quadrantReading("short_covering")).toBe("short covering (▲ price ▼ OI)");
  });

  it("treats anything but the four served values as unclassified", () => {
    expect(quadrantOf("long_buildup")).toBe("long_buildup");
    expect(quadrantOf(null)).toBeNull();
    expect(quadrantOf("20")).toBeNull();
    expect(quadrantOf("long_build")).toBeNull(); // the CMP-186 prop spelling is not the wire's
    expect(quadrantOf("toString")).toBeNull();
    // keys a plain object lookup would answer for, and near misses
    for (const k of [
      undefined,
      "",
      "LONG_BUILDUP",
      "Long_Buildup",
      "constructor",
      "__proto__",
      "hasOwnProperty",
    ]) {
      expect(quadrantOf(k)).toBeNull();
    }
  });

  it("has a null entry in the lookup: the neutral absent hatch (BQ-4)", () => {
    expect(styleFor(null)).toBe(NO_QUADRANT_STYLE);
    expect(NO_QUADRANT_STYLE.hatch).toBe("pattern.hatch.absent");
    expect(styleFor("long_buildup")).toBe(QUADRANT_STYLE.long_buildup);
  });
});

describe("pattern floor (Q12, PROPOSED)", () => {
  it.each([
    [12, "tips"],
    [10, "tips"],
    [9.9, "width"],
    [6, "width"],
    [5, "lod"],
    [4, "lod"],
    [3, "ribbon"],
  ])("%s px per bar -> %s", (px, rung) => {
    expect(floorRung(px)).toBe(rung);
  });
});

describe("buildOiBars", () => {
  const model = buildOiBars(DELTA_SERIES, QUADRANT_SERIES, FIXTURE_ROWS, FIXTURE_BAR_MS, "BTCUSDT");

  it("keeps the served decimals exactly and takes the unit from the series", () => {
    expect(model.bars.map((b) => b.delta)).toEqual(["20", "12.5", "-8.25", null, "0", "-3"]);
    expect(model.deltaUnit).toBe("qty");
  });

  it("words 'no OI sample' only where the OI feed has no point for the bar (BQ-3)", () => {
    expect(model.bars.map((b) => b.reason)).toEqual([
      null,
      null,
      null,
      "no_sample",
      "unclassified",
      null,
    ]);
    expect(countBars(model.bars)).toMatchObject({
      noSample: 1,
      unclassified: 1,
      unclassifiedTotal: 2,
    });
  });

  it("never infers a quadrant from the deltas or the price (BQ-4)", () => {
    // a positive delta with a null served quadrant stays unclassified, whatever the signs say
    const m = buildOiBars(
      { unit: "qty", points: [{ t: DELTA_SERIES.points[0]?.t ?? "", v: "500" }] },
      { unit: "enum", points: [{ t: DELTA_SERIES.points[0]?.t ?? "", v: null }] },
      FIXTURE_ROWS,
      FIXTURE_BAR_MS,
      "BTCUSDT",
    );
    expect(m.bars[0]?.quadrant).toBeNull();
    expect(countBars(m.bars).byQuadrant).toEqual({
      long_buildup: 0,
      short_covering: 0,
      short_buildup: 0,
      long_unwind: 0,
    });
  });

  it("handles one series only, out-of-order and duplicate bars", () => {
    const [p0, p1] = DELTA_SERIES.points;
    const m = buildOiBars(
      {
        unit: "qty",
        points: [p1 ?? { t: "", v: null }, { t: p0?.t ?? "", v: "1" }, p0 ?? { t: "", v: null }],
      },
      { unit: "enum", points: [] },
      FIXTURE_ROWS,
      FIXTURE_BAR_MS,
      "BTCUSDT",
    );
    expect(m.bars.map((b) => b.delta)).toEqual(["20", "12.5"]); // sorted, the later duplicate wins
    expect(m.bars.every((b) => b.quadrant === null)).toBe(true);
    expect(m.barMs).toBe(FIXTURE_BAR_MS);
    expect(m.symbol).toBe("BTCUSDT");
  });

  it("finds a sample on a mid-bar row of a finer bar, by binary search", () => {
    const row = FIXTURE_ROWS[0];
    if (row === undefined) throw new Error("fixture");
    const m = buildOiBars(
      { unit: "qty", points: [{ t: new Date(row.tMs + 60_000).toISOString(), v: "1" }] },
      { unit: "enum", points: [] },
      [...FIXTURE_ROWS].reverse(),
      60_000,
      "BTCUSDT",
    );
    expect(m.bars[0]?.reason).toBe("unclassified");
  });

  it("counts each served quadrant", () => {
    expect(countBars(model.bars).byQuadrant).toEqual({
      long_buildup: 1,
      short_covering: 1,
      short_buildup: 1,
      long_unwind: 1,
    });
  });
});

describe("unclassified announcement (D04 LR-5)", () => {
  it("is a material change only past max(3 bars, 10%), the same at 0 and N (hysteresis)", () => {
    expect(isMaterialChange(0, 1, 50)).toBe(false); // hysteresis: the same rule at 0
    expect(isMaterialChange(0, 5, 50)).toBe(true);
    expect(isMaterialChange(5, 0, 50)).toBe(true);
    expect(isMaterialChange(2, 0, 50)).toBe(false);
    expect(isMaterialChange(4, 6, 50)).toBe(false);
    expect(isMaterialChange(4, 9, 50)).toBe(true); // 10% of 50 = 5
    expect(isMaterialChange(4, 4, 50)).toBe(false);
    expect(isMaterialChange(10, 12, 10)).toBe(false); // the 3-bar floor
    // at a larger window the 10% share governs: 200 bars -> 20
    expect(isMaterialChange(10, 29, 200)).toBe(false);
    expect(isMaterialChange(10, 30, 200)).toBe(true);
    expect(isMaterialChange(30, 10, 200)).toBe(true);
  });

  it("words AN-5 when every unclassified bar has no sample", () => {
    expect(announcement(3, 3)).toBe("3 bars unclassified, no open-interest sample.");
    expect(announcement(1, 0)).toBe("1 bar unclassified.");
    expect(announcement(0, 0)).toBe("All bars classified.");
  });

  const opts = { ready: true, enabled: true, resetKey: "a", clearKey: "ready" };

  it("does not announce on mount, then once per material change", () => {
    const onAnnounce = vi.fn();
    const { result, rerender } = renderHook(
      ({ n }: { n: number }) => useUnclassifiedAnnouncement(n, n, 50, onAnnounce, opts),
      { initialProps: { n: 2 } },
    );
    expect(result.current).toBe("");
    rerender({ n: 3 }); // 1 bar: not material
    expect(result.current).toBe("");
    rerender({ n: 7 });
    expect(result.current).toBe("7 bars unclassified, no open-interest sample.");
    expect(onAnnounce).toHaveBeenCalledTimes(1);
    rerender({ n: 7 });
    expect(onAnnounce).toHaveBeenCalledTimes(1);
  });

  it("reports a steady gap once per seed, not on every render", () => {
    const onSeed = vi.fn();
    const o = { ...opts, onSeed };
    const { rerender } = renderHook(
      (p: { n: number; o: typeof o }) => useUnclassifiedAnnouncement(p.n, p.n, 50, undefined, p.o),
      { initialProps: { n: 4, o } },
    );
    rerender({ n: 4, o });
    expect(onSeed).toHaveBeenCalledTimes(1);
    expect(onSeed).toHaveBeenCalledWith(4, 4);
    rerender({ n: 4, o: { ...o, resetKey: "b" } }); // a new seed
    expect(onSeed).toHaveBeenCalledTimes(2);
    rerender({ n: 0, o: { ...o, resetKey: "c" } }); // a seed of zero says nothing
    expect(onSeed).toHaveBeenCalledTimes(2);
  });

  it("never speaks for a count flapping 0, 1, 0, 1", () => {
    const { result, rerender } = renderHook(
      ({ n }: { n: number }) => useUnclassifiedAnnouncement(n, n, 50, undefined, opts),
      { initialProps: { n: 0 } },
    );
    for (const n of [1, 0, 1, 0, 1]) rerender({ n });
    expect(result.current).toBe("");
  });

  it("seeds on the first render with bars, not at mount without them (F1)", () => {
    const { result, rerender } = renderHook(
      ({ n, ready }: { n: number; ready: boolean }) =>
        useUnclassifiedAnnouncement(n, n, 50, undefined, { ...opts, ready }),
      { initialProps: { n: 0, ready: false } },
    );
    rerender({ n: 9, ready: true });
    expect(result.current).toBe("");
    rerender({ n: 20, ready: true });
    expect(result.current).toBe("20 bars unclassified, no open-interest sample.");
  });

  it("re-seeds on a symbol or interval change, clears on a phase change, and is silent while off", () => {
    const { result, rerender } = renderHook(
      (p: { n: number; o: typeof opts }) =>
        useUnclassifiedAnnouncement(p.n, p.n, 50, undefined, p.o),
      { initialProps: { n: 2, o: opts } },
    );
    rerender({ n: 9, o: opts });
    expect(result.current).not.toBe("");
    rerender({ n: 9, o: { ...opts, clearKey: "loading" } });
    expect(result.current).toBe("");
    rerender({ n: 30, o: { ...opts, clearKey: "loading", resetKey: "b" } }); // a new symbol
    expect(result.current).toBe("");
    rerender({ n: 50, o: { ...opts, clearKey: "loading", resetKey: "b", enabled: false } });
    expect(result.current).toBe("");
    rerender({ n: 50, o: { ...opts, clearKey: "loading", resetKey: "b" } }); // baseline followed
    expect(result.current).toBe("");
  });
});

describe("deltaUnitLabel (display only)", () => {
  it("shows no unit word when the series carries none", () => {
    expect(deltaUnitLabel(null, "BTC")).toBeNull();
    const m = buildOiBars({ points: [] }, { points: [] }, [], FIXTURE_BAR_MS, "BTCUSDT");
    expect(m.deltaUnit).toBeNull();
  });

  it("maps the kind qty to the instrument's base coin, else leaves it", () => {
    expect(deltaUnitLabel("qty", "BTC")).toBe("BTC");
    expect(deltaUnitLabel("qty", "1000PEPE")).toBe("1000PEPE");
    expect(deltaUnitLabel("qty", null)).toBe("qty");
    expect(deltaUnitLabel("qty", undefined)).toBe("qty");
    expect(deltaUnitLabel("qty", "")).toBe("qty");
    expect(deltaUnitLabel("contracts", "BTC")).toBe("contracts");
  });
});

describe("analytics", () => {
  it("reports the counts only", () => {
    const report = vi.fn();
    const a = createOiAnalytics(report);
    createQuadrantAnalytics(report).unclassifiedCounted("BTCUSDT", 3, 2);
    createQuadrantAnalytics(report).unclassifiedSeeded("BTCUSDT", 4, 1);
    a.metricToggled("delta", false);
    expect(report).toHaveBeenNthCalledWith(1, {
      name: "oi_panel.unclassified_counted",
      symbol: "BTCUSDT",
      total: 3,
      no_sample: 2,
    });
    expect(report).toHaveBeenNthCalledWith(2, {
      name: "oi_panel.unclassified_seeded",
      symbol: "BTCUSDT",
      total: 4,
      no_sample: 1,
    });
    expect(report).toHaveBeenNthCalledWith(3, {
      name: "oi_panel.metric_toggled",
      mode: "delta",
      quadrant_colouring: false,
    });
  });
});
