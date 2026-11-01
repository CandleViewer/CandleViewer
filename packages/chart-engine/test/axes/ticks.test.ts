// E11-S06 tick model (README BQ-186 to BQ-188, BQ-201, BQ-203): the price ladder across three
// magnitudes and tick sizes 0.01 / 0.5 / 1, E11-D02 §4.2's worked sets, log and percent, the
// 23-step time ladder from 10 s to 5 years and E11-D02 §5.4's worked steps, calendar ranks, zones,
// and the gutter cache's re-measure rule.
import { describe, expect, it, vi } from "vitest";
import { TickSet } from "../../src/axes/decimate.js";
import {
  civil,
  createZoned,
  daysFrom,
  decimalsOf,
  formatNumber,
  ZoneClock,
} from "../../src/axes/format.js";
import { fixedMeasure, GutterCache, GUTTER_MIN_PX } from "../../src/axes/gutter.js";
import { majorOf, niceStep, PRICE_KIND, PriceTicks } from "../../src/axes/price-ticks.js";
import { RANK, rankOf, TIME_LADDER, TimeTicks, timeStep } from "../../src/axes/time-ticks.js";
import { minuteMap } from "../interaction/fixtures.js";
import { ChartViewport, type PaneTransform } from "../../src/viewport/index.js";

/** A 600 px pane showing [low, high] in price at `tick`. */
function pane(
  low: number,
  high: number,
  tick: number,
  mode: PaneTransform["scaleMode"] = "linear",
) {
  const vp = new ChartViewport();
  vp.setSize(1200, 600, 1);
  vp.setPanePlot(0, 0, 600);
  vp.setPriceInfo(0, 0, tick);
  vp.setPriceRange(0, low / tick, high / tick);
  const p = vp.panes[0] as PaneTransform;
  p.scaleMode = mode;
  p.logReason = null;
  return vp;
}

function labels(vp: ChartViewport, gap = 40): { set: TickSet; ticks: PriceTicks } {
  const set = new TickSet();
  const ticks = new PriceTicks();
  ticks.update(vp, 0, 0, 600, gap, 13, set);
  return { set, ticks };
}
/** The candidates anchored on the pane (the rest are the hidden margin, BQ-189). */
const inPane = (set: TickSet): number[] =>
  [...Array(set.n).keys()].filter(
    (i) => (set.at[i] as number) >= 0 && (set.at[i] as number) <= 600,
  );
const texts = (set: TickSet): string[] => inPane(set).map((i) => set.text[i] ?? "");
const majors = (set: TickSet): string[] =>
  inPane(set).flatMap((i) => (set.tier[i] === 1 ? [set.text[i] ?? ""] : []));

describe("price-ticks: nice-number steps", () => {
  it.each([
    [0.3, 1, 1],
    [1.2, 1, 2],
    [3, 1, 5],
    [7, 1, 10],
    [26.7, 1, 50],
    [130, 1, 200],
    [4_100, 1, 5_000],
    [0.016, 0, 0.02],
    [0.0031, 0, 0.005],
  ])("ideal %d (floor %d) steps to %d", (ideal, floor, step) => {
    expect(niceStep(ideal, floor)).toBeCloseTo(step, 9);
  });

  it.each([
    [50, 100],
    [25, 50],
    [0.5, 1],
    [2, 10],
    [0.2, 1],
    [20, 100],
    [1, 5],
  ])("a %d label step has its majors every %d (E11-D02 §4.2)", (step, major) => {
    expect(majorOf(step)).toBeCloseTo(major, 9);
  });

  it.each([
    // E11-D02 §4.2's worked sets: pane 600 px, compact G = 40 (dense 32).
    ["BTCUSDT", 63_900, 64_300, 0.5, 40, "63,900.0", 9, ["63,900.0", "64,000.0", "64,100.0"]],
    ["ETHUSDT", 3_240, 3_260, 0.01, 40, "3,240.00", 11, ["3,240.00", "3,250.00", "3,260.00"]],
    ["SOLUSDT", 150.2, 152.6, 0.001, 40, "150.200", 13, ["151.000", "152.000"]],
    ["BTCUSDT dense", 63_900, 64_300, 0.5, 32, "63,900.0", 17, ["63,900.0", "63,950.0"]],
  ])("%s: step and majors per the worked set", (_n, lo, hi, tick, gap, first, count, major) => {
    const { set, ticks } = labels(pane(lo, hi, tick), gap);
    expect(inPane(set)).toHaveLength(count);
    expect(texts(set)[0]).toBe(first);
    expect(majors(set).slice(0, major.length)).toEqual(major);
    expect(ticks.kind).toBe(PRICE_KIND.price);
  });

  it("steps are whole ticks at tick sizes 0.01, 0.5 and 1 across three magnitudes", () => {
    for (const tick of [0.01, 0.5, 1]) {
      for (const span of [10, 1_000, 100_000]) {
        const { set } = labels(pane(50_000, 50_000 + span, tick));
        expect(inPane(set).length).toBeGreaterThanOrEqual(2);
        for (let i = 0; i < set.n; i += 1) {
          const v = set.value[i] as number; // the label's absolute tick
          expect(Number.isInteger(v)).toBe(true);
        }
        const step = (set.value[1] as number) - (set.value[0] as number);
        expect([1, 2, 5]).toContain(step / 10 ** Math.floor(Math.log10(step)));
      }
    }
  });

  it("log: decades are majors with 2× and 5× between; a narrow window falls back to linear", () => {
    const { set } = labels(pane(0.9, 1_100, 0.01, "log"));
    const want = ["1.00", "2.00", "5.00", "10.00", "20.00", "50.00", "100.00", "200.00", "500.00"];
    expect(texts(set)).toEqual([...want, "1,000.00"]);
    expect(majors(set)).toEqual(["1.00", "10.00", "100.00", "1,000.00"]);
    expect(inPane(labels(pane(63_900, 64_300, 0.5, "log")).set)).toHaveLength(9);
  });

  it("percent: the 0.1 / 0.2 / 0.5 ladder in displayValue space, signed", () => {
    const vp = pane(99, 104, 0.01, "percent");
    (vp.panes[0] as PaneTransform).anchorTick = 100 / 0.01;
    const { set, ticks } = labels(vp);
    expect(ticks.kind).toBe(PRICE_KIND.percent);
    expect(texts(set)).toContain("+1.0%");
    expect(texts(set)).toContain("0.0%");
    expect(texts(set)).toContain("-0.5%");
  });

  it("no tick size yet: no candidates", () => {
    const vp = new ChartViewport();
    vp.setPanePlot(0, 0, 600);
    expect(labels(vp).set.n).toBe(0);
  });
});

describe("time-ticks: the 23-step ladder", () => {
  it("has E11-D02 §5.2's 23 steps, ascending", () => {
    expect(TIME_LADDER).toHaveLength(23);
    expect([...TIME_LADDER].sort((a, b) => a - b)).toEqual(TIME_LADDER);
  });

  const MIN = 60_000;
  const name = (i: number): number => (TIME_LADDER[i] as number) / 1000;
  it.each([
    // E11-D02 §5.4: 1 m bars, plot 1200 px, compact G = 80.
    [MIN, 50, 120],
    [MIN, 12, 600],
    [MIN, 3, 1_800],
    [MIN, 0.5, 10_800],
    [MIN, 0.05, 172_800],
    [MIN, 200, 60],
  ])("bars of %d ms at %d px each step every %d s", (bar, px, seconds) => {
    expect(name(timeStep(bar, px / bar, 80))).toBe(seconds);
  });

  it.each([
    // Spans from 10 s to 5 years over 1200 px.
    [1_000, 10_000, 1],
    [1_000, 600_000, 60],
    [MIN, 86_400_000, 7_200],
    [86_400_000, 5 * 365 * 86_400_000, 31_536_000],
  ])("a %d ms bar over %d ms picks %d s", (bar, span, seconds) => {
    expect(name(timeStep(bar, 1200 / span, 80))).toBe(seconds);
  });

  it("ranks a time by the coarsest calendar unit it falls on", () => {
    const z = createZoned();
    const at = (y: number, m: number, d: number, ms = 0): number => {
      civil(daysFrom(y, m, d), z);
      z.ms = ms;
      return rankOf(z);
    };
    expect(at(2027, 1, 1)).toBe(RANK.year);
    expect(at(2026, 10, 1)).toBe(RANK.quarter);
    expect(at(2026, 11, 1)).toBe(RANK.month);
    expect(at(2026, 10, 26)).toBe(RANK.week); // a Monday
    expect([RANK.day, RANK.twoDays]).toContain(at(2026, 10, 27));
    expect(at(2026, 10, 27, 13 * 3_600_000)).toBe(RANK.hour);
    expect(at(2026, 10, 27, 13.5 * 3_600_000)).toBe(11); // 30 m
    expect(at(2026, 10, 27, 1)).toBe(-1);
  });
});

describe("time-ticks: label text per rank (E11-D02 §5.3)", () => {
  /** The candidates anchored on a 1200 px plot over `n` bars of `barUs` at `spacing` px. */
  function labelsAt(barUs: number, spacing: number, n = 20_000): string[] {
    const t0 = minuteMap().indexToTime(0);
    const vp = new ChartViewport({
      length: n,
      barDurationUs: barUs,
      indexToTime: (i) => (i >= 0 && i < n ? t0 + i * barUs : Number.NaN),
      timeToIndex: (t) => (t < t0 ? -1 : Math.min(n - 1, Math.floor((t - t0) / barUs))),
    });
    vp.setSize(1200, 600, 1);
    vp.scrollTo(n / 2, spacing);
    const set = new TickSet();
    new TimeTicks(new ZoneClock()).update(vp, 1200, 80, (t) => t.length * 6.6, set);
    return [...Array(set.n).keys()]
      .filter((i) => (set.at[i] as number) >= 0 && (set.at[i] as number) <= 1200)
      .map((i) => set.text[i] ?? "");
  }

  it("an hour view puts the date in place of midnight; a day view, dates only", () => {
    const hours = labelsAt(60e6, 0.5); // 3 h step over 40 h
    expect(hours).toContain("03:00");
    expect(hours.some((t) => /^\d\d \w{3}$/.test(t))).toBe(true);
    expect(labelsAt(60e6, 0.05).every((t) => /^(\d\d \w{3}|\w{3})$/.test(t))).toBe(true);
  });

  it("daily bars over years: months and years", () => {
    const years = labelsAt(86_400e6, 0.25, 4_000); // ~13 y over 1200 px: 1 y step
    expect(years.every((t) => /^\d{4}$/.test(t))).toBe(true);
    const months = labelsAt(86_400e6, 4, 4_000); // 300 days: 1 M step
    expect(months.some((t) => /^[A-Z][a-z]{2}$/.test(t))).toBe(true);
  });

  it("seconds bars label seconds", () => {
    expect(labelsAt(1e6, 40).every((t) => /^\d\d:\d\d:\d\d$/.test(t))).toBe(true);
  });

  it("a span past the ladder's top keeps its last step", () => {
    expect(timeStep(86_400_000, 1e-12, 80)).toBe(TIME_LADDER.length - 1);
  });
});

describe("format", () => {
  it("decimals and thousands separators", () => {
    expect([decimalsOf(0.5), decimalsOf(0.01), decimalsOf(1), decimalsOf(0.001)]).toEqual([
      1, 2, 0, 3,
    ]);
    expect(formatNumber(64_050.5, 1)).toBe("64,050.5");
    expect(formatNumber(-1_234_567, 0)).toBe("-1,234,567");
    expect(formatNumber(-0.001, 2)).toBe("0.00");
  });

  it("civil dates round-trip across eras", () => {
    const z = createZoned();
    for (const d of [-719_468, -1, 0, 20_000, 2_932_896]) {
      civil(d, z);
      expect(daysFrom(z.year, z.month, z.day)).toBe(d);
    }
  });

  it("a zone's offset comes from one formatter; an unknown zone is UTC (BQ-203)", () => {
    const summer = Date.UTC(2026, 6, 1, 12);
    expect(new ZoneClock("Europe/Berlin").offset(summer)).toBe(2 * 3_600_000);
    expect(new ZoneClock("Europe/Berlin").toUtc(summer + 2 * 3_600_000)).toBe(summer);
    const bad = new ZoneClock("Not/AZone");
    expect([bad.timeZone, bad.offset(summer)]).toEqual(["UTC", 0]);
  });

  it("caches offsets per UTC hour and stays exact across a DST jump (BQ-203)", () => {
    const jump = Date.UTC(2026, 2, 8, 7); // New York: 02:00 EST becomes 03:00 EDT
    const clock = new ZoneClock("America/New_York");
    const want = (t: number): number => (t < jump ? -5 : -4) * 3_600_000;
    for (const t of [jump + 1_000, jump - 1_000, jump, jump - 3_600_000, jump + 3_599_000]) {
      expect(clock.offset(t)).toBe(want(t));
      expect(clock.offset(t)).toBe(want(t)); // the second read is the cached one
    }
    // Lord Howe moves 30 min at 15:30 UTC: that hour holds the jump, so it is answered exactly.
    const half = Date.UTC(2026, 9, 3, 15, 30);
    const howe = new ZoneClock("Australia/Lord_Howe");
    for (const [t, h] of [
      [half - 1_800_000, 10.5],
      [half - 1_000, 10.5],
      [half, 11],
      [half + 1_799_000, 11],
      [half - 1_000, 10.5],
    ] as const) {
      expect(howe.offset(t)).toBe(h * 3_600_000);
    }
    const spy = vi.spyOn(Intl.DateTimeFormat.prototype, "formatToParts");
    try {
      const t = Date.UTC(2026, 6, 1, 12, 30);
      clock.offset(t);
      const fresh = spy.mock.calls.length;
      expect(fresh).toBe(2); // the hour's first and last second
      for (let s = 0; s < 3_600; s += 7) clock.offset(Date.UTC(2026, 6, 1, 12) + s * 1000);
      expect(spy.mock.calls.length).toBe(fresh); // the rest of the hour is cached
    } finally {
      spy.mockRestore();
    }
  });

  it("a repeated time pass in a DST zone reads no formatter (no per-frame allocation)", () => {
    const vp = new ChartViewport(minuteMap());
    vp.setSize(1200, 600, 1);
    vp.scrollTo(1_000, 4);
    const ticks = new TimeTicks(new ZoneClock("America/New_York"));
    const set = new TickSet();
    ticks.update(vp, 1200, 80, (t) => t.length * 6.6, set);
    const spy = vi.spyOn(Intl.DateTimeFormat.prototype, "formatToParts");
    try {
      ticks.update(vp, 1200, 80, (t) => t.length * 6.6, set);
      expect(set.n).toBeGreaterThan(3);
      expect(spy).not.toHaveBeenCalled();
    } finally {
      spy.mockRestore();
    }
  });
});

describe("gutter: remeasures only on formatter, font or magnitude change", () => {
  it("is the widest label plus 8 px, at least 48, measured once per class", () => {
    const g = new GutterCache();
    const m = fixedMeasure();
    const w = g.widthFor(PRICE_KIND.price, 1, 4, m); // "99,999.9": 8 × 6.6 px
    expect(w).toBe(Math.ceil(8 * 6.6) + 8);
    for (let i = 0; i < 100; i += 1) g.widthFor(PRICE_KIND.price, 1, 4, m);
    expect(g.remeasures).toBe(1);
    expect(g.widthFor(PRICE_KIND.price, 0, 0, m)).toBe(GUTTER_MIN_PX);
    g.widthFor(PRICE_KIND.percent, 0, 0, m);
    g.widthFor(PRICE_KIND.percent, 0, 0, fixedMeasure(13));
    expect(g.remeasures).toBe(4);
  });
});
