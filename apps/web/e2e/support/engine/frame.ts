// The Node half of the harness feed (layout: apps/web/e2e/engine-harness/barsFrame.ts): the header, and
// one binary frame of time f64, open/high/low/close i32, volume f32, tiled in that order.
import { BAR_MS, type Bars } from "./fixtures";

export interface FeedHeader {
  readonly fixture: string;
  readonly count: number;
  readonly priceOrigin: number;
  readonly tickSize: number;
  readonly barDurationUs: number;
  readonly initialVisible: number;
}

export function encodeHeader(b: Bars): FeedHeader {
  return {
    fixture: b.name,
    count: b.time.length,
    priceOrigin: b.priceOrigin,
    tickSize: b.tickSize,
    barDurationUs: BAR_MS * 1000,
    initialVisible: b.initialVisible,
  };
}

export function encodeFrame(b: Bars): Uint8Array {
  const n = b.time.length;
  const buf = new ArrayBuffer(n * 28);
  new Float64Array(buf, 0, n).set(b.time);
  const ints = new Int32Array(buf, n * 8, n * 4);
  ints.set(b.open, 0);
  ints.set(b.high, n);
  ints.set(b.low, 2 * n);
  ints.set(b.close, 3 * n);
  new Float32Array(buf, n * 24, n).set(b.volume);
  return new Uint8Array(buf);
}
