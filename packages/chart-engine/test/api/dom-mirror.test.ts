// E11-S13 PR-2: the DOM mirror (26 §12, E06-D03 D1/D2/D4; E47-D06 R-3, R-6, §4, §8 at #5443
// head 7a9002db, if it merges as is). Unit level: the mirror driven with built windows and rows.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  DomMirror,
  MIRROR_TABLE_LABEL,
  type MirrorDeps,
  type MirrorNode,
} from "../../src/a11y/DomMirror.js";
import { buildA11yRows, priceDecimalsOf, readA11yRows } from "../../src/a11y/rows.js";
import {
  A11Y_WINDOW_ROWS_MAX,
  computeA11yWindow,
  EMPTY_A11Y_WINDOW,
  type A11yWindow,
} from "../../src/a11y/window.js";
import { FakeDocument, FakeElement } from "./fake-dom.js";
import { makeBars } from "../../bench/scenes/dom-mirror.js";

const view = { leftIndex: 0, barSpacing: 8, plotWidth: 800, dpr: 1 };
const lod = { candles: 0, footprint: 0 };

function windowAt(bars: ReturnType<typeof makeBars>, cursorBar: number, rows = 60): A11yWindow {
  const w = { ...EMPTY_A11Y_WINDOW };
  const left = Math.max(0, bars.length - 100);
  return computeA11yWindow(w, bars, { ...view, leftIndex: left }, cursorBar * 60e6, lod, rows);
}

let doc: FakeDocument;
let root: FakeElement;
let frames: (() => void)[];
let timers: { cb: () => void; at: number }[];
let clock: number;
let labels: string[];

function mirror(): DomMirror {
  const deps: MirrorDeps = {
    root: root as unknown as MirrorNode,
    createElement: (tag) => doc.createElement(tag) as unknown as MirrorNode,
    schedule: (cb) => void frames.push(cb),
    now: () => clock,
    setTimer: (cb, ms) => {
      const t = { cb, at: clock + ms };
      timers.push(t);
      return () => void timers.splice(timers.indexOf(t), 1);
    },
    setCanvasLabel: (text) => void labels.push(text),
    timeZone: "UTC",
  };
  return new DomMirror(deps);
}

const frame = (): void => {
  for (const cb of frames.splice(0)) cb();
};
const advance = (ms: number): void => {
  clock += ms;
  for (const t of timers.filter((x) => x.at <= clock)) {
    timers.splice(timers.indexOf(t), 1);
    t.cb();
  }
};
const table = (): FakeElement => {
  const t = root.children[0];
  if (t === undefined) throw new Error("no mirror table");
  return t;
};
const body = (): FakeElement[] => table().children[1]?.children ?? [];
const text = (tr: FakeElement | undefined): string[] =>
  (tr?.children ?? []).map((td) => td.textContent);

beforeEach(() => {
  doc = new FakeDocument();
  root = doc.createElement("div");
  frames = [];
  timers = [];
  clock = 0;
  labels = [];
  FakeElement.markupWrites = 0;
});

afterEach(() => {
  expect(FakeElement.markupWrites).toBe(0); // textContent only, never markup (ticket Security)
});

describe("the mirror table (26 §12)", () => {
  it("test_mirror_100k_bars_materialises_at_most_the_cap (AC4)", () => {
    const bars = makeBars(100_000);
    const m = mirror();
    const w = windowAt(bars, 99_999);
    m.update(w, buildA11yRows(w, bars, -1), bars.length);
    frame();
    expect(body()).toHaveLength(60);
    expect(table().getAttribute("aria-rowcount")).toBe("100001");
    expect(body()[0]?.getAttribute("aria-rowindex")).toBe(String(99_940 + 2));
    expect(body()[59]?.getAttribute("aria-current")).toBe("true");
    expect(m.counters.mirrorNodes).toBe(11 + 60 * 8);
    // The opt-in cap: 200 rows and at most 1,800 nodes (D06 §4), whatever a message claims.
    const wide = windowAt(bars, 50_000, 500);
    m.update(wide, buildA11yRows(wide, bars, w.firstBar), bars.length);
    frame();
    expect(body().length).toBeLessThanOrEqual(A11Y_WINDOW_ROWS_MAX);
    expect(m.counters.mirrorNodes).toBeLessThanOrEqual(1800);
  });

  it("test_mirror_candle_l2_still_draws_one_row_per_bar (D06 R-3)", () => {
    const bars = makeBars(10_000);
    const m = mirror();
    // 0.25 px a bar at dpr 2: candle L2 packs 2 bars per device-px column; the rows do not.
    const thin = { ...view, leftIndex: 0, barSpacing: 0.25, dpr: 2 };
    const w = computeA11yWindow({ ...EMPTY_A11Y_WINDOW }, bars, thin, 5_000 * 60e6, {
      candles: 2,
      footprint: 3,
    });
    expect(w).toMatchObject({ candleTier: "L2", barsPerColumn: 2 });
    m.update(w, buildA11yRows(w, bars, -1), bars.length);
    frame();
    expect(body()).toHaveLength(60);
    expect(body().map((tr) => Number(tr.getAttribute("aria-rowindex")) - 2)).toEqual(
      Array.from({ length: 60 }, (_, i) => w.firstBar + i),
    );
    const at = (i: number): string =>
      (bars.priceOrigin + (bars.close[w.firstBar + i] ?? 0) * bars.tickSize).toFixed(1);
    expect(body().map((tr) => text(tr)[4])).toEqual(Array.from({ length: 60 }, (_, i) => at(i)));
  });

  it("test_mirror_row_matches_renderer_values_with_text_content", () => {
    const bars = makeBars(10);
    const m = mirror();
    const w = windowAt(bars, 9);
    m.update(w, buildA11yRows(w, bars, -1), bars.length);
    frame();
    const row = text(body()[3]);
    expect(row.slice(1, 5)).toEqual(
      [bars.open[3], bars.high[3], bars.low[3], bars.close[3]].map((t) =>
        (bars.priceOrigin + (t ?? 0) * bars.tickSize).toFixed(1),
      ),
    );
    expect(row[0]).toContain("1970");
    expect(row[6]?.startsWith("+") || row[6]?.startsWith("-") || row[6] === "0").toBe(true);
  });

  it("test_mirror_shift_keeps_row_node_identity", () => {
    const bars = makeBars(1000);
    const m = mirror();
    const w1 = windowAt(bars, 500);
    m.update(w1, buildA11yRows(w1, bars, -1), bars.length);
    frame();
    const before = new Map(body().map((tr) => [tr.getAttribute("aria-rowindex"), tr]));
    const cells = body()[10]?.children[4];
    const w2 = windowAt(bars, 503);
    const rows = buildA11yRows(w2, bars, w1.firstBar);
    expect(rows?.shifted).toBe(3);
    m.update(w2, rows, bars.length);
    frame();
    const after = body();
    expect(after.map((tr) => Number(tr.getAttribute("aria-rowindex")) - 2)).toEqual(
      Array.from({ length: 60 }, (_, i) => w2.firstBar + i),
    );
    const kept = after.filter((tr) => before.get(tr.getAttribute("aria-rowindex")) === tr);
    expect(kept).toHaveLength(57); // a shift of 3 moves 3 rows (D2)
    expect(after[7]?.children[4]).toBe(cells);
    expect(m.counters.mirrorRewindows).toBe(0);
    const w0 = windowAt(bars, 497); // and back: rows enter at the head, in bar order
    m.update(w0, buildA11yRows(w0, bars, w2.firstBar), bars.length);
    frame();
    expect(body().map((tr) => Number(tr.getAttribute("aria-rowindex")) - 2)).toEqual(
      Array.from({ length: 60 }, (_, i) => w0.firstBar + i),
    );
    expect(body().filter((tr) => tr.getAttribute("aria-current") === "true")).toHaveLength(1);
  });

  it("test_mirror_distant_jump_counts_one_rewindow_and_reuses_the_pool", () => {
    const bars = makeBars(10_000);
    const m = mirror();
    const w1 = windowAt(bars, 9_000);
    m.update(w1, buildA11yRows(w1, bars, -1), bars.length);
    frame();
    const created = doc.created.length;
    const w2 = windowAt(bars, 100);
    m.update(w2, buildA11yRows(w2, bars, w1.firstBar), bars.length);
    frame();
    expect(m.counters.mirrorRewindows).toBe(1);
    expect(doc.created.length).toBe(created); // pooled: no node is created for the jump
  });

  it("test_mirror_writes_once_per_frame_latest_wins", () => {
    const bars = makeBars(500);
    const m = mirror();
    const w1 = windowAt(bars, 100);
    const w2 = windowAt(bars, 300);
    m.update(w1, buildA11yRows(w1, bars, -1), bars.length);
    m.update(w2, buildA11yRows(w2, bars, -1), bars.length);
    expect(frames).toHaveLength(1);
    expect(body()).toHaveLength(0); // nothing is written before the frame
    frame();
    expect(body()[0]?.getAttribute("aria-rowindex")).toBe(String(w2.firstBar + 2));
    expect(m.counters.mirrorUpdateMs).toBeGreaterThanOrEqual(0);
  });

  it("test_mirror_mismatched_rows_count_a_desync_and_draw_nothing", () => {
    const bars = makeBars(500);
    const m = mirror();
    const w = windowAt(bars, 300);
    const stale = buildA11yRows(windowAt(bars, 100), bars, -1);
    m.update(w, stale, bars.length);
    frame();
    expect(m.counters.desyncDetected).toBe(1);
    expect(body()).toHaveLength(0);
    m.update(EMPTY_A11Y_WINDOW, null, 0);
    frame();
    // A header-only table claims no rows (review item 4): aria-rowcount only while rows are drawn.
    expect(table().getAttribute("aria-rowcount")).toBeNull();
  });

  it("test_mirror_structure_is_d4_label_and_time_row_header", () => {
    const bars = makeBars(100);
    const m = mirror();
    const w = windowAt(bars, 99);
    m.update(w, buildA11yRows(w, bars, -1), bars.length);
    frame();
    expect(table().getAttribute("aria-label")).toBe(MIRROR_TABLE_LABEL);
    expect(MIRROR_TABLE_LABEL).toBe("Bars around the cursor");
    const cells = body()[0]?.children ?? [];
    expect(cells.map((e) => e.tagName)).toEqual(["TH", "TD", "TD", "TD", "TD", "TD", "TD"]);
    expect(cells[0]?.getAttribute("scope")).toBe("row");
    const head = table().children[0]?.children[0]?.children ?? [];
    expect(head.every((th) => th.getAttribute("scope") === "col")).toBe(true);
  });

  it("test_mirror_clamps_an_over_cap_window_itself", () => {
    const bars = makeBars(1000);
    const m = mirror();
    // A window wider than the cap reaches the mirror unclamped (computeA11yWindow never does this).
    const w: A11yWindow = { ...windowAt(bars, 999), firstBar: 0, lastBar: 499, cursorBar: 10 };
    const rows = buildA11yRows(w, bars, -1);
    expect(rows?.count).toBe(A11Y_WINDOW_ROWS_MAX);
    m.update(w, rows, bars.length);
    frame();
    expect(body()).toHaveLength(A11Y_WINDOW_ROWS_MAX);
    expect(m.counters.mirrorNodes).toBe(11 + A11Y_WINDOW_ROWS_MAX * 8);
    expect(m.counters.desyncDetected).toBe(0);
  });

  it("test_mirror_unchanged_rows_format_nothing", () => {
    const bars = makeBars(300);
    const m = mirror();
    const w = windowAt(bars, 299);
    m.update(w, buildA11yRows(w, bars, -1), bars.length);
    frame();
    // `format` is an accessor on the Intl prototype: count its reads (each format is one read).
    const proto = Intl.DateTimeFormat.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "format");
    const get = desc?.get;
    if (desc === undefined || get === undefined) throw new Error("no Intl format accessor");
    let timeFormats = 0;
    Object.defineProperty(proto, "format", {
      ...desc,
      get(this: Intl.DateTimeFormat) {
        timeFormats += 1;
        return get.call(this) as unknown;
      },
    });
    const priceFmt = vi.spyOn(Number.prototype, "toFixed");
    try {
      m.update(w, buildA11yRows(w, bars, w.firstBar), bars.length);
      frame();
      expect(timeFormats).toBe(0);
      expect(priceFmt).toHaveBeenCalledTimes(0);
      bars.close[299] = (bars.close[299] ?? 0) + 5; // one changed cell formats once
      m.update(w, buildA11yRows(w, bars, w.firstBar), bars.length);
      frame();
      expect(timeFormats).toBe(0);
      expect(priceFmt.mock.calls.length).toBeGreaterThanOrEqual(1);
      expect(priceFmt.mock.calls.length).toBeLessThanOrEqual(2); // the cell, plus the label's close
    } finally {
      Object.defineProperty(proto, "format", desc);
      priceFmt.mockRestore();
    }
  });
});

describe("the canvas img label (D06 §8 L-1, R-6 cadence)", () => {
  it("test_canvas_img_label_updates_on_data_change_at_the_cadence (AC6)", () => {
    const bars = makeBars(300);
    const m = mirror();
    const w = windowAt(bars, 299);
    m.update(w, buildA11yRows(w, bars, -1), bars.length);
    frame();
    const close = (bars.priceOrigin + (bars.close[299] ?? 0) * bars.tickSize).toFixed(1);
    expect(labels).toEqual([expect.stringContaining(`100 bars visible, last close ${close}`)]);
    bars.close[299] = (bars.close[299] ?? 0) + 7; // a tick patches the last bar
    m.update(w, buildA11yRows(w, bars, w.firstBar), bars.length);
    frame();
    bars.close[299] = (bars.close[299] ?? 0) + 3;
    m.update(w, buildA11yRows(w, bars, w.firstBar), bars.length);
    frame();
    expect(labels).toHaveLength(1); // throttled: one per 2 s
    advance(2000);
    const latest = (bars.priceOrigin + (bars.close[299] ?? 0) * bars.tickSize).toFixed(1);
    expect(labels).toEqual([expect.any(String), expect.stringContaining(`last close ${latest}`)]);
  });

  it("test_mirror_dispose_removes_the_table_and_stops_the_label_timer", () => {
    const bars = makeBars(300);
    const m = mirror();
    const w = windowAt(bars, 299);
    m.update(w, buildA11yRows(w, bars, -1), bars.length);
    frame();
    bars.close[299] = 1;
    m.update(w, buildA11yRows(w, bars, w.firstBar), bars.length);
    frame();
    expect(timers).toHaveLength(1);
    m.dispose();
    m.dispose();
    expect(root.children).toHaveLength(0);
    expect(timers).toHaveLength(0);
    m.update(w, null, 1);
    expect(frames).toHaveLength(0);
  });
});

describe("rows on the wire (E06-D03 D9)", () => {
  it("test_rows_reader_rejects_malformed_and_oversized_rows", () => {
    const bars = makeBars(300);
    const rows = buildA11yRows(windowAt(bars, 200), bars, -1);
    expect(readA11yRows(rows)).toBe(rows);
    expect(readA11yRows(null)).toBeNull();
    expect(readA11yRows({ ...rows, count: 201 })).toBeNull();
    expect(readA11yRows({ ...rows, close: new Float64Array(60) })).toBeNull();
    expect(readA11yRows({ ...rows, tickSize: Number.NaN })).toBeNull();
    expect(readA11yRows({ ...rows, priceDecimals: 101 })).toBeNull(); // toFixed would throw
    expect(readA11yRows({ ...rows, priceDecimals: 1.5 })).toBeNull();
    expect(readA11yRows({ ...rows, priceDecimals: -1 })).toBeNull();
    expect(readA11yRows({ ...rows, dirty: [] })).toBeNull();
    expect(buildA11yRows(EMPTY_A11Y_WINDOW, bars, -1)).toBeNull();
    expect([priceDecimalsOf(0.1), priceDecimalsOf(0.0005), priceDecimalsOf(1)]).toEqual([1, 4, 0]);
    expect([priceDecimalsOf(0), priceDecimalsOf(1e-13)]).toEqual([0, 12]);
  });
});
