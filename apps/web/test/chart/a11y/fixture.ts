/**
 * A typed SCR-045 fixture: the `26` §8 arrays the chart is given (BTCUSDT 1m, tick 0.5, qty step 0.001), built
 * deterministically. Synthetic shapes only (no exchange payload): the table reads typed arrays, not Bybit frames.
 */
import type { ChartTableSeries } from "../../../src/chart/a11y/series";

/** 2026-10-20 13:00:00 UTC in µs. */
export const T0_US = Date.UTC(2026, 9, 20, 13, 0, 0) * 1000;
export const MINUTE_US = 60_000_000;

export interface FixtureOptions {
  readonly bars: number;
  /** Footprint levels per bar; 0 = footprint off. */
  readonly levels?: number;
}

export function makeSeries({ bars, levels = 3 }: FixtureOptions): ChartTableSeries {
  const time = new Float64Array(bars);
  const open = new Int32Array(bars);
  const high = new Int32Array(bars);
  const low = new Int32Array(bars);
  const close = new Int32Array(bars);
  const volume = new Float32Array(bars);
  for (let i = 0; i < bars; i++) {
    time[i] = T0_US + i * MINUTE_US;
    const base = 20 + (i % 7);
    open[i] = base;
    high[i] = base + 2;
    low[i] = base - 1;
    close[i] = base + 1;
    volume[i] = 1.5 + (i % 3);
  }
  const candles = { time, open, high, low, close, volume, priceOrigin: 64000, tickSize: 0.5 };
  const series = { candles, priceDecimals: 1, qtyDecimals: 3, intervalMs: 60_000 };
  if (levels === 0) return series;
  const offsets = new Uint32Array(bars + 1);
  const cells = bars * levels;
  const price = new Int32Array(cells);
  const bid = new Float32Array(cells);
  const ask = new Float32Array(cells);
  for (let i = 0; i < bars; i++) {
    offsets[i + 1] = (i + 1) * levels;
    for (let k = 0; k < levels; k++) {
      const c = i * levels + k;
      price[c] = (low[i] ?? 0) + k; // ascending in storage; the table shows them descending
      bid[c] = k === 0 ? 0.4 : 0.1;
      ask[c] = k === levels - 1 ? 0.5 : 0.1;
    }
  }
  const footprint = {
    barIndexOffsets: offsets,
    cellPriceLevel: price,
    cellBidVol: bid,
    cellAskVol: ask,
    cellTradeCount: new Uint16Array(cells),
    priceOrigin: 64000,
    tickSize: 0.5,
  };
  return { ...series, footprint };
}
