// The harness-only feed's frame layout (BQ-05: not the 23-ws-protocol.md market-data protocol).
// One text frame (the header, JSON) then one binary frame: the six columns tiled in this order,
// each aligned (time 8 B, the rest 4 B): time f64, open/high/low/close i32, volume f32.
// Encoder: apps/web/e2e/support/engine/frame.ts.
import type { CandleData } from "@candleviewer/chart-engine";

export interface BarsHeader {
  readonly fixture: string;
  readonly count: number;
  readonly priceOrigin: number;
  readonly tickSize: number;
  readonly barDurationUs: number;
  /** How many trailing bars the first viewport shows. */
  readonly initialVisible: number;
}

export function decodeBarsFrame(h: BarsHeader, buf: ArrayBuffer): CandleData {
  const n = h.count;
  if (buf.byteLength !== n * (8 + 4 * 5)) throw new RangeError("bars frame: wrong byte length");
  const i32 = (k: number): Int32Array => new Int32Array(buf, n * 8 + k * n * 4, n);
  return {
    time: new Float64Array(buf, 0, n),
    open: i32(0),
    high: i32(1),
    low: i32(2),
    close: i32(3),
    volume: new Float32Array(buf, n * 8 + 4 * n * 4, n),
    priceOrigin: h.priceOrigin,
    tickSize: h.tickSize,
  };
}
