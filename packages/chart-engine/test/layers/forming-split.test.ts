// E12-S09 AC5 (#421; E12-D06 §5.4, `14`:754): at L2 the forming bar is never frozen into an
// aggregate. The decimator folds bars [first, `foldEnd`), so the forming bar is outside every
// column; `ColumnEntries` appends it as its own entry at its own device column, from its own
// O / H / L / C, so each tick rewrites (and patches) that one entry. With the forming flag
// cleared (the bar confirmed), it folds like any other bar.
import { describe, expect, it } from "vitest";
import {
  CANDLE_STRIDE,
  ColumnEntries,
  foldEnd,
  formingLast,
  type RangePatchSink,
} from "../../src/layers/index.js";
import { BAR_FLAG, BarStore, type MutationRange } from "../../src/model/index.js";
import { columnOf, foldOracle, rowsBatch } from "./column-oracle.js";

const PX = 0.25; // 4 bars a device column
const ROWS = Array.from({ length: 12 }, (_, i) => [100 + i, 104 + i, 98 + i, 101 + i]);

function setup() {
  const store = new BarStore();
  const flags = new Uint8Array(ROWS.length);
  flags[ROWS.length - 1] = BAR_FLAG.forming;
  store.append(rowsBatch(ROWS, flags));
  const patched: string[] = [];
  const sink: RangePatchSink = {
    patch: (_: string, r: MutationRange) => patched.push(`${r.from}-${r.to}`),
  };
  const e = new ColumnEntries(8, sink);
  e.nodes.push("span");
  const write = (): number =>
    e.write(foldOracle(store, 0, PX, foldEnd(store), 8), store, columnOf(store.length - 1, 0, PX));
  return { store, e, patched, write };
}
const entry = (e: ColumnEntries, j: number): number[] =>
  Array.from(e.ints.subarray(j * CANDLE_STRIDE, j * CANDLE_STRIDE + 5));

describe("AC5: the forming bar at L2", () => {
  it("is its own entry at its own column, never folded into the shared column", () => {
    const { store, e, write } = setup();
    expect([formingLast(store), foldEnd(store)]).toEqual([true, 11]);
    expect(write()).toBe(4); // columns 0, 1, 2 (bars 8..10), then the forming bar
    expect(entry(e, 2).slice(0, 4)).toEqual([108, 114, 106, 111]); // bars 8..10 only
    expect(entry(e, 3)).toEqual([111, 115, 109, 112, (2 << 4) | 0]); // bar 11, column 2, up
  });

  it("each tick rewrites and patches the forming entry alone", () => {
    const { store, e, patched, write } = setup();
    write();
    patched.length = 0;
    const tick = rowsBatch([[111, 130, 109, 125]], Uint8Array.of(BAR_FLAG.forming));
    store.append({ ...tick, time: Float64Array.of(11 * 60e6) }, true); // a merge: the live bar
    write();
    expect(patched).toEqual(["3-4"]);
    expect(entry(e, 3).slice(0, 4)).toEqual([111, 130, 109, 125]);
    expect(entry(e, 2).slice(0, 4)).toEqual([108, 114, 106, 111]); // the aggregate unchanged
  });

  it("folds normally once confirmed (no forming flag)", () => {
    const { store, e, write } = setup();
    const done = rowsBatch([[111, 115, 109, 112]]);
    store.append({ ...done, time: Float64Array.of(11 * 60e6) }, true);
    expect([formingLast(store), foldEnd(store)]).toEqual([false, 12]);
    expect(write()).toBe(3);
    expect(entry(e, 2).slice(0, 4)).toEqual([108, 115, 106, 112]);
  });

  it("an empty store, or a forming column outside the strip, adds no entry", () => {
    const e = new ColumnEntries(2);
    const empty = new BarStore();
    expect([formingLast(empty), foldEnd(empty)]).toEqual([false, 0]);
    const none = { ints: new Int32Array(0), stride: 4, count: 0, firstColumn: 0 };
    expect(e.write(none, empty, 0)).toBe(0);
    const { store } = setup();
    for (const col of [-1, Number.NaN, 2 ** 28]) expect(e.write(none, store, col)).toBe(0);
    expect(e.write(none, store, 1)).toBe(1);
  });
});
