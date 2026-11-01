// E11-S07 test helpers: a viewport with 1 px per tick (y = 600 - tick over a 600 px plot) and a
// tiny bar source in the `BarSource` shape (µs time, ticks from priceOrigin).
import type { BarSource } from "../../src/overlays/readout.js";
import { ChartViewport, type IndexTimeMap } from "../../src/viewport/index.js";

export const MIN_US = 60e6;
/** 2026-10-14 14:00 UTC in µs. */
export const T0 = Date.UTC(2026, 9, 14, 14, 0) * 1000;

export function timeMap(n: number): IndexTimeMap {
  return {
    length: n,
    indexToTime: (i) => (i >= 0 && i < n ? T0 + i * MIN_US : Number.NaN),
    timeToIndex: (t) => Math.min(n - 1, Math.floor((t - T0) / MIN_US)),
  };
}

/** `n` bars, `spacing` px each from leftIndex `left`; ticks [0, 600] fill the 600 px plot. */
export function viewport(n: number, spacing = 10, left = 0, width = 1200): ChartViewport {
  const vp = new ChartViewport(timeMap(n));
  vp.setSize(width, 600, 1);
  vp.setPanePlot(0, 0, 600);
  vp.setPriceRange(0, 0, 600);
  vp.setPriceInfo(0, 64_000, 1);
  vp.barSpacing = spacing;
  vp.leftIndex = left;
  return vp;
}

export interface Bars {
  time: Float64Array;
  open: Int32Array;
  high: Int32Array;
  low: Int32Array;
  close: Int32Array;
  volume: Float32Array | null;
  delta: Float32Array | null;
  priceOrigin: number;
  tickSize: number;
  length: number;
}

/** Bar i: O 200+i, H 300+i, L 100+i, C 250+i, volume 1000+i, delta i - 5 (ticks over 64,000). */
export function source(n: number, tickSize = 1): Bars & BarSource {
  const b: Bars = {
    time: new Float64Array(n),
    open: new Int32Array(n),
    high: new Int32Array(n),
    low: new Int32Array(n),
    close: new Int32Array(n),
    volume: new Float32Array(n),
    delta: new Float32Array(n),
    priceOrigin: 64_000,
    tickSize,
    length: n,
  };
  for (let i = 0; i < n; i += 1) {
    b.time[i] = T0 + i * MIN_US;
    b.open[i] = 200 + i;
    b.high[i] = 300 + i;
    b.low[i] = 100 + i;
    b.close[i] = 250 + i;
    (b.volume as Float32Array)[i] = 1000 + i;
    (b.delta as Float32Array)[i] = i - 5;
  }
  return b;
}
