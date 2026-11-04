// E24-S01 (#776) slice 1: reconciliation of backfill and live points, and gap detection (test plan).
import { describe, expect, it } from "vitest";
import {
  parseCoverage,
  parsePoint,
  type HistoryPoint,
} from "../../../src/features/derivatives/oi/history";
import {
  LIVE_GAP_MS,
  MAX_LIVE_GAPS,
  MAX_LIVE_ROWS,
  OiSeries,
  type LiveTick,
} from "../../../src/features/derivatives/oi/series";
import { parseTickerItem } from "../../../src/features/derivatives/oi/ticker";
import { coverageOf, recordedRestPoints, recordedTickerItems } from "./support/oiFixtures";

const MIN = 60_000;
const REST = recordedRestPoints();
const HISTORY = REST.map(parsePoint).filter((p): p is HistoryPoint => p !== null);
const COVERAGE = parseCoverage({ coverage: coverageOf(REST) });
if (COVERAGE === null) throw new Error("coverage fixture");
const LAST_REST = HISTORY[HISTORY.length - 1]?.tMs ?? 0;
const TICKS = recordedTickerItems()
  .map((i) => parseTickerItem(i, "BTCUSDT"))
  .filter((t): t is NonNullable<typeof t> => t !== null);
const TICK0 = TICKS[0];
if (TICK0 === undefined) throw new Error("ticker fixture");
const WINDOW = { fromMs: HISTORY[0]?.tMs ?? 0, toMs: (TICK0.tsMs ?? 0) + 60 * MIN };

/** A recorded tick moved in time only (its values unchanged). */
const at = (tsMs: number, over: Partial<LiveTick> = {}): LiveTick => ({ ...TICK0, tsMs, ...over });

const series = (barMs = MIN) => new OiSeries(barMs, WINDOW);

describe("OI series reconciliation", () => {
  it("lays history then live, ascending, with the live bar aligned and forming", () => {
    const s = series();
    s.setHistory(HISTORY, COVERAGE, 5 * MIN);
    for (const t of TICKS) s.addLive(t);
    const rows = s.rows();
    expect(
      rows.slice(0, HISTORY.length).every((r) => r.source === "rest" && r.valueUsdt === null),
    ).toBe(true);
    const live = rows.slice(HISTORY.length);
    expect(live.length).toBeGreaterThan(0);
    expect(live.every((r) => r.source === "ws_ticker" && r.tMs % MIN === 0)).toBe(true);
    expect(live.map((r) => r.forming)).toEqual(live.map((_, i) => i === live.length - 1));
    expect(s.latest()?.base).toBe(TICKS[TICKS.length - 1]?.base);
    expect(s.latest()?.valueUsdt).toBe(TICKS[TICKS.length - 1]?.valueUsdt);
  });

  it("drops a live item whose aligned bar starts at or before the last backfilled point", () => {
    const s = series();
    s.setHistory(HISTORY, COVERAGE, 5 * MIN);
    expect(s.addLive(at(LAST_REST))).toBe(false);
    expect(s.addLive(at(LAST_REST - MIN))).toBe(false);
    expect(s.addLive(at(LAST_REST + 1))).toBe(true); // inside the last history bar: readout only
    expect(s.rows()).toHaveLength(HISTORY.length);
    expect(s.counters.superseded).toBe(3);
    expect(s.addLive(at(LAST_REST + MIN))).toBe(true);
  });

  it("on 5 min bars, a tick inside the last history bucket never makes a second row for it", () => {
    const s = series(5 * MIN);
    s.setHistory(HISTORY, COVERAGE, 5 * MIN);
    expect(s.addLive(at(LAST_REST + 3 * MIN))).toBe(true); // the readout moves (A1)
    expect(s.rows().filter((r) => r.tMs === LAST_REST)).toHaveLength(1);
    expect(s.rows()).toHaveLength(HISTORY.length);
    expect(s.addLive(at(LAST_REST + 5 * MIN + 1000))).toBe(true);
    expect(
      s
        .rows()
        .map((r) => r.tMs)
        .slice(-2),
    ).toEqual([LAST_REST, LAST_REST + 5 * MIN]);

    // the same rule when history lands after live: the bar it now covers gives way
    const late = series(5 * MIN);
    late.addLive(at(LAST_REST + 3 * MIN));
    late.addLive(at(LAST_REST + 5 * MIN + 1000));
    late.setHistory(HISTORY, COVERAGE, 5 * MIN);
    const times = late.rows().map((r) => r.tMs);
    expect(new Set(times).size).toBe(times.length);
    expect(times.slice(-2)).toEqual([LAST_REST, LAST_REST + 5 * MIN]);
  });

  it("shows the newest tick inside the last history bucket in the readout, the rows unchanged (A1)", () => {
    const s = series(5 * MIN); // history 12:00 on 5 min bars, a tick at 12:03
    s.setHistory(HISTORY, COVERAGE, 5 * MIN);
    expect(s.latest()).toMatchObject({ source: "rest", valueUsdt: null });
    const tick = at(LAST_REST + 3 * MIN);
    expect(s.addLive(tick)).toBe(true);
    expect(s.latest()).toEqual({
      tMs: LAST_REST,
      spanMs: 5 * MIN,
      base: tick.base,
      valueUsdt: tick.valueUsdt,
      source: "ws_ticker",
      forming: true,
      asOfMs: LAST_REST + 3 * MIN,
    });
    expect(s.rows()[s.rows().length - 1]?.source).toBe("rest");
    expect(s.addLive(at(LAST_REST + 2 * MIN))).toBe(false); // older than the readout's tick
    const v = s.version;
    expect(s.addLive(at(LAST_REST + 4 * MIN))).toBe(false); // newer, same values: nothing to redraw
    expect(s.version).toBe(v);
    expect(s.latest()?.asOfMs).toBe(LAST_REST + 4 * MIN); // its time is still the newest seen
    expect(s.addLive(at(LAST_REST + 4 * MIN + 1, { base: "1.000" }))).toBe(true);
    expect(s.latest()?.base).toBe("1.000");
  });

  it("ends the last 5 min history span where a 1 m live bar begins, so they never overlap", () => {
    const s = series(MIN);
    s.setHistory(HISTORY, COVERAGE, 5 * MIN);
    s.addLive(at(LAST_REST + 3 * MIN + 500));
    const rows = s.rows();
    const lastHistory = rows[HISTORY.length - 1];
    const firstLive = rows[HISTORY.length];
    expect(lastHistory?.spanMs).toBe(3 * MIN);
    expect(lastHistory?.clipped).toBe(true);
    expect(rows[0]?.clipped).toBeUndefined();
    expect((lastHistory?.tMs ?? 0) + (lastHistory?.spanMs ?? 0)).toBe(firstLive?.tMs);
    expect(rows[0]?.spanMs).toBe(5 * MIN);
  });

  it("bounds the live seams it keeps and prunes those before the window", () => {
    const s = new OiSeries(MIN, { fromMs: 0, toMs: Number.MAX_SAFE_INTEGER });
    let t = 1_000_000;
    for (let i = 0; i <= MAX_LIVE_GAPS + 10; i += 1) {
      s.addLive(at(t));
      t += LIVE_GAP_MS + 1;
    }
    const live = s.gaps().filter((g) => g.kind === "live");
    expect(live).toHaveLength(MAX_LIVE_GAPS);
    expect(live[live.length - 1]?.toMs).toBe(t - LIVE_GAP_MS - 1);

    const w = new OiSeries(MIN, { fromMs: 5_000_000, toMs: 6_000_000 });
    w.addLive(at(1_000_000));
    w.addLive(at(2_000_000)); // a seam wholly before the window
    w.addLive(at(5_500_000)); // one that reaches into it
    expect(w.gaps()).toEqual([{ fromMs: 2_000_000, toMs: 5_500_000, kind: "live" }]);
  });

  it("lets a late backfill replace the live bars it covers", () => {
    const s = series();
    s.addLive(at(LAST_REST - 2 * MIN));
    s.addLive(at(LAST_REST + 2 * MIN));
    expect(s.rows()).toHaveLength(2);
    s.setHistory(HISTORY, COVERAGE, 5 * MIN);
    expect(s.rows()).toHaveLength(HISTORY.length + 1);
    expect(s.latest()?.tMs).toBe(LAST_REST + 2 * MIN);
  });

  it("lets a late backfill drop the live seams it covers, and keep the ones past it", () => {
    const s = series();
    s.addLive(at(LAST_REST - 3 * MIN));
    s.addLive(at(LAST_REST - 2 * MIN)); // a seam inside what history will cover
    s.addLive(at(LAST_REST + 2 * MIN));
    s.addLive(at(LAST_REST + 4 * MIN)); // a seam past it
    expect(s.gaps().filter((g) => g.kind === "live")).toHaveLength(3);
    s.setHistory(HISTORY, COVERAGE, 5 * MIN);
    expect(s.gaps()).toEqual([
      { fromMs: LAST_REST - 2 * MIN, toMs: LAST_REST + 2 * MIN, kind: "live" },
      { fromMs: LAST_REST + 2 * MIN, toMs: LAST_REST + 4 * MIN, kind: "live" },
    ]);
  });

  it("keeps at most MAX_LIVE_ROWS live bars, the oldest out first", () => {
    const s = series();
    const t0 = Date.parse("2026-10-20T00:00:00Z");
    for (let i = 0; i < MAX_LIVE_ROWS + 5; i += 1) s.addLive(at(t0 + i * MIN, { base: String(i) }));
    const rows = s.rows();
    expect(rows).toHaveLength(MAX_LIVE_ROWS);
    expect(rows[0]?.base).toBe("5");
    expect(s.latest()?.base).toBe(String(MAX_LIVE_ROWS + 4));
  });

  it("marks the span of the evicted live bars as one live gap, never a line", () => {
    const sec = 1_000; // ticks within LIVE_GAP_MS, so no seam of their own
    const s = series(sec);
    s.setHistory(HISTORY, COVERAGE, 5 * MIN);
    const t0 = LAST_REST + 5 * MIN;
    for (let i = 0; i < MAX_LIVE_ROWS; i += 1) s.addLive(at(t0 + i * sec, { base: String(i) }));
    expect(s.gaps().filter((g) => g.kind === "live")).toEqual([]);
    s.addLive(at(t0 + MAX_LIVE_ROWS * sec, { base: "x" })); // evicts the bar at t0
    s.addLive(at(t0 + (MAX_LIVE_ROWS + 1) * sec, { base: "y" })); // and the next
    const live = s.gaps().filter((g) => g.kind === "live");
    expect(live).toEqual([{ fromMs: LAST_REST + 5 * MIN, toMs: t0 + 2 * sec, kind: "live" }]);
  });

  it("keeps the last write per bar, and a repeated value only moves the as-of time", () => {
    const s = series();
    const t = Date.parse("2026-10-20T10:00:05Z");
    expect(s.addLive(at(t))).toBe(true);
    const v = s.version;
    expect(s.addLive(at(t + 1000))).toBe(true);
    expect(s.version).toBe(v + 1);
    expect(s.rows()).toHaveLength(1);
    expect(s.rows()[0]?.asOfMs).toBe(t + 1000);
    expect(s.latest()?.asOfMs).toBe(t + 1000);
    expect(s.addLive(at(t + 2000, { base: "1.000" }))).toBe(true);
    expect(s.rows()).toHaveLength(1);
    expect(s.latest()?.base).toBe("1.000");
    expect(s.latest()?.asOfMs).toBe(t + 2000);
  });

  it("refuses an out-of-order item", () => {
    const s = series();
    s.addLive(at(2_000_000));
    expect(s.addLive(at(1_000_000))).toBe(false);
    expect(s.counters.late).toBe(1);
  });

  it("reports the store's recorded gaps and a failed backfill as gaps, never a line", () => {
    const s = series();
    const gap = { fromMs: HISTORY[3]?.tMs ?? 0, toMs: HISTORY[6]?.tMs ?? 0 };
    s.setHistory(HISTORY, { ...COVERAGE, gaps: [gap] }, 5 * MIN);
    expect(s.gaps()).toEqual([{ ...gap, kind: "recorded" }]);

    const f = series();
    f.setHistoryFailed();
    expect(f.gaps()).toEqual([{ fromMs: WINDOW.fromMs, toMs: WINDOW.toMs, kind: "failed" }]);
    f.addLive(at(TICK0.tsMs));
    expect(f.gaps()[0]).toEqual({
      fromMs: WINDOW.fromMs,
      toMs: TICK0.tsMs - (TICK0.tsMs % MIN),
      kind: "failed",
    });
    f.setHistory(HISTORY, COVERAGE, 5 * MIN); // a retry that succeeds clears it
    expect(f.gaps()).toEqual([]);
  });

  it("starts a failed retry's gap after the rows an earlier load left, never over them", () => {
    const s = series();
    s.setHistory(HISTORY, COVERAGE, 5 * MIN);
    s.setHistoryFailed();
    expect(s.rows()).toHaveLength(HISTORY.length);
    expect(s.gaps()).toEqual([{ fromMs: LAST_REST + 5 * MIN, toMs: WINDOW.toMs, kind: "failed" }]);
    s.addLive(at(LAST_REST + 8 * MIN));
    const failed = s.gaps().filter((g) => g.kind === "failed");
    expect(failed).toEqual([
      { fromMs: LAST_REST + 5 * MIN, toMs: LAST_REST + 8 * MIN, kind: "failed" },
    ]);
    expect(failed.every((g) => g.fromMs >= LAST_REST + 5 * MIN)).toBe(true);
  });

  it("opens a live gap after a reset or a silence past the store's 10 s rule", () => {
    const s = series();
    const t = Date.parse("2026-10-20T10:00:00Z");
    s.addLive(at(t));
    s.addLive(at(t + LIVE_GAP_MS)); // exactly 10 s: no gap
    expect(s.gaps()).toEqual([]);
    s.addLive(at(t + 2 * LIVE_GAP_MS + 1));
    expect(s.gaps()).toEqual([
      { fromMs: t + LIVE_GAP_MS, toMs: t + 2 * LIVE_GAP_MS + 1, kind: "live" },
    ]);
    s.seam();
    const v = s.version;
    expect(s.addLive(at(t + 2 * LIVE_GAP_MS + 2))).toBe(true); // same bar, same value: the seam alone shows
    expect(s.version).toBeGreaterThan(v);
    expect(s.gaps()).toHaveLength(2);
  });

  it("states coverage.from and the native interval for the empty state and the note", () => {
    const s = series();
    expect(s.coverageFromMs()).toBeNull();
    expect(s.nativeInterval()).toBeNull();
    s.setHistory([], { ...COVERAGE, fromMs: null, toMs: null }, 5 * MIN);
    expect(s.hasHistory()).toBe(false);
    expect(s.coverageFromMs()).toBeNull();
    s.setHistory(HISTORY, COVERAGE, 5 * MIN);
    expect(s.coverageFromMs()).toBe(HISTORY[0]?.tMs);
    expect(s.nativeInterval()).toBe("5min");
  });
});
