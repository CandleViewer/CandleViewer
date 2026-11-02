// E12-S09 L2 column marks (BQ-03, E12-D06 §5.4): parts 7 / 8 in the geometry twin (a hairline
// column at its device x, the neutral tint; the span down solid, up `dash.1-1`, O = C a dot) at
// DPR 1, 1.5 and 2; `ColumnEntries` (empty and out-of-range columns skipped, bounded by its
// preallocated width, only changed entries patched, growth only in `reserve`); and the series'
// L2 frame: the same two batches drawing the entries, the L1 mark without them.
import { describe, expect, it } from "vitest";
import {
  CANDLE_DIR,
  CANDLE_PART,
  CANDLE_STRIDE,
  CandleRing,
  CandleSeries,
  candleGeometry,
  ColumnEntries,
  columnRect,
  FILL,
  fillMode,
  GEOM,
  MAX_COLUMN,
  PALETTE,
  partColor,
  type RangePatchSink,
} from "../../src/layers/index.js";
import { BarStore, type MutationRange } from "../../src/model/index.js";
import { projectRel } from "../../src/viewport/transform.js";
import { rowsBatch } from "./column-oracle.js";

const K = Float64Array.of(10, -2, 500, 0, 0, 600, 0, 0);
const geom = (dpr: number): Float32Array => {
  const g = new Float32Array(8);
  candleGeometry(1, dpr, g, 2);
  return g;
};
/** A source of `cols` (minLow, maxHigh, firstOpen, lastClose) rows from device column `first`. */
const source = (cols: readonly (readonly number[])[], first = 0, stride = 4) => ({
  ints: Int32Array.from(cols.flatMap((c) => [...c, ...Array<number>(stride - 4).fill(0)])),
  stride,
  count: cols.length,
  firstColumn: first,
});

describe("L2 column parts in the geometry twin (D06 §5.4)", () => {
  it.each([1, 1.5, 2])("dpr %f: a max(1, floor(dpr)) column at its device x", (dpr) => {
    const g = geom(dpr);
    const hair = Math.max(1, Math.floor(dpr));
    expect(g[GEOM.tier]).toBe(2);
    const out = new Float64Array(4);
    columnRect(CANDLE_PART.columnWick, 37, 10, 30, 5, 20, K, 0, g, out);
    expect(Array.from(out)).toEqual([37, projectRel(K, 30), hair, 50]);
    columnRect(CANDLE_PART.columnSpan, 37, 10, 30, 5, 20, K, 0, g, out);
    expect(Array.from(out)).toEqual([37, projectRel(K, 20), hair, 20]);
    columnRect(CANDLE_PART.columnSpan, 37, 12, 30, 5, 12, K, 0, g, out); // O = C: the dot
    expect(Array.from(out)).toEqual([37, Math.floor(476 - hair / 2 + 0.5), hair, hair]);
    columnRect(CANDLE_PART.columnWick, 2, 7, 7, 7, 7, K, 0, g, out); // zero range: a hairline
    expect(out[3]).toBe(hair);
  });

  it("colours: the neutral tint wick; the span by direction, O = C neutral", () => {
    expect(partColor(CANDLE_PART.columnWick, CANDLE_DIR.down)).toBe(PALETTE.neutral);
    const span = [CANDLE_DIR.up, CANDLE_DIR.down, CANDLE_DIR.doji, CANDLE_DIR.zeroRange];
    expect(span.map((d) => partColor(CANDLE_PART.columnSpan, d))).toEqual([
      PALETTE.up,
      PALETTE.down,
      PALETTE.wick,
      PALETTE.wick,
    ]);
  });

  it("fill: the up span dash.1-1, the down span and the wick solid", () => {
    const g = geom(1);
    expect(fillMode(CANDLE_PART.columnSpan, CANDLE_DIR.up, 1, g)).toBe(FILL.dash);
    expect(fillMode(CANDLE_PART.columnSpan, CANDLE_DIR.down, 1, g)).toBe(FILL.solid);
    expect(fillMode(CANDLE_PART.columnWick, CANDLE_DIR.up, 1, g)).toBe(FILL.solid);
  });
});

describe("ColumnEntries: the source's columns as candle instances", () => {
  it("writes [open, high, low, close, column << 4 | dir]; empty columns are skipped", () => {
    const e = new ColumnEntries(8);
    const n = e.write(
      source(
        [
          [5, 30, 10, 20],
          [1, 0, 0, 0],
          [5, 9, 9, 6],
        ],
        100,
        6,
      ),
    );
    expect(n).toBe(2);
    expect(Array.from(e.ints.subarray(0, 2 * CANDLE_STRIDE))).toEqual([
      10,
      30,
      5,
      20,
      (100 << 4) | CANDLE_DIR.up,
      9,
      9,
      5,
      6,
      (102 << 4) | CANDLE_DIR.down,
    ]);
  });

  it("is bounded by its width: columns past it, below 0 or past MAX_COLUMN are dropped", () => {
    const e = new ColumnEntries(2);
    expect(e.capacity).toBe(3);
    expect(
      e.write(
        source([
          [1, 2, 1, 2],
          [1, 2, 1, 2],
          [1, 2, 1, 2],
          [1, 2, 1, 2],
        ]),
      ),
    ).toBe(2);
    expect(e.write(source([[1, 2, 1, 2]], -1))).toBe(0);
    expect(e.write(source([[1, 2, 1, 2]], MAX_COLUMN + 1))).toBe(0);
    expect(e.write(source([[1, 2, 1, 2]], 0.5))).toBe(0);
    expect(e.write({ ints: new Int32Array(8), stride: 3, count: 2, firstColumn: 0 })).toBe(0);
    for (const w of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(new ColumnEntries(w).capacity).toBe(1); // the forming entry alone
    }
  });

  it("patches only the entries that changed; grows only in reserve, as a new array", () => {
    const seen: string[] = [];
    const sink: RangePatchSink = {
      patch: (id: string, r: MutationRange) => seen.push(`${id} ${r.from} ${r.to}`),
    };
    const e = new ColumnEntries(4, sink);
    e.nodes.push("wick", "span");
    const cols = [
      [1, 9, 2, 3],
      [1, 9, 2, 3],
      [1, 9, 2, 3],
    ];
    e.write(source(cols));
    expect(seen).toEqual(["wick 0 3", "span 0 3"]);
    seen.length = 0;
    e.write(source(cols));
    expect([seen, e.dirtyFrom, e.dirtyTo]).toEqual([[], 0, 0]);
    cols[2] = [1, 9, 2, 8]; // a tick re-folds the trailing column only
    e.write(source(cols));
    expect(seen).toEqual(["wick 2 3", "span 2 3"]);
    const data = e.data;
    e.reserve(3);
    expect([e.data, e.grown]).toEqual([data, 1]);
    e.reserve(64);
    expect([e.data === data, e.grown, e.capacity]).toEqual([false, 2, 65]);
  });
});

describe("CandleSeries at L2: the same two batches draw the entries", () => {
  it("parts 7 / 8 over (0, -1, count); the L1 mark without entries; back to L0", () => {
    const c = new CandleSeries(new CandleRing(), "bars");
    const e = new ColumnEntries(4);
    e.write(
      source([
        [1, 9, 2, 3],
        [1, 9, 3, 2],
      ]),
    );
    c.frame(0.5, 2, 0, -1, 0, 0, 2, e);
    expect(c.blocks.slice(0, 2).map((b) => [...b.ints, b.instances, b.vertices])).toEqual([
      [CANDLE_PART.columnWick, 0, -1, 2, 2, 4],
      [CANDLE_PART.columnSpan, 0, -1, 2, 2, 4],
    ]);
    expect(c.geom[GEOM.tier]).toBe(2);
    c.frame(0.5, 2, 0, -1, 0, 0, 2, null);
    expect(c.blocks.slice(0, 2).map((b) => [b.ints[0], b.instances])).toEqual([
      [CANDLE_PART.wick, -1],
      [CANDLE_PART.body, -1],
    ]);
    c.frame(12, 1);
    expect(c.blocks.slice(0, 2).map((b) => b.ints[0])).toEqual([
      CANDLE_PART.stem,
      CANDLE_PART.ticks,
    ]);
    expect(c.geom[GEOM.tier]).toBe(0);
  });

  it("an L2 column is not picked by the bar hit-test (PR 2's)", () => {
    const store = new BarStore();
    const ring = new CandleRing();
    ring.sync(store, store.append(rowsBatch([[10, 12, 8, 11]])));
    const c = new CandleSeries(ring);
    c.drawable = true;
    const hit = { index: -1, part: -1, distancePx: Infinity };
    c.frame(10, 1);
    expect(c.hitTest(5, 480, 0, K, 0, 0, 4, hit)).toBe(true);
    c.frame(0.5, 1, 0, -1, 0, 0, 2, new ColumnEntries(2));
    expect(c.hitTest(5, 480, 0, K, 0, 0, 4, hit)).toBe(false);
  });
});
