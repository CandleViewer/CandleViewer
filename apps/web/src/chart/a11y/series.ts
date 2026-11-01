/**
 * SCR-045's read model over the series the chart is given (`26` §8 `CandleData` + `FootprintData`): the same typed
 * arrays, the same RBAC-filtered data, no fetch. Rows are read on demand for the drawn window only; the one O(n) pass
 * is the CVD prefix, in scaled integers so it is exact.
 */
import type { CandleData, FootprintData } from "@candleviewer/chart-engine";
import { IMBALANCE_WORDS } from "./copy";
import { qtyScaled, scaledToDecimal, ticksToDecimal, type BarFields } from "./format";

export interface ChartTableSeries {
  readonly candles: CandleData;
  /** Absent when footprint is off: no delta, CVD or levels. */
  readonly footprint?: FootprintData | undefined;
  /** The instrument's price digits (the axis labels' digits). */
  readonly priceDecimals: number;
  /** The instrument's `qty_step` digits. */
  readonly qtyDecimals: number;
  /** The bar interval, for the time format. */
  readonly intervalMs: number;
  /** `FootprintOptions.imbalanceRatio` (default 3.0 = 300 %). */
  readonly imbalanceRatio?: number;
}

export type ImbalanceWord = (typeof IMBALANCE_WORDS)[keyof typeof IMBALANCE_WORDS];

export interface LevelFields {
  readonly price: string;
  readonly bid: string;
  readonly ask: string;
  readonly delta: string;
  readonly imbalance: ImbalanceWord;
}

export const barCount = (s: ChartTableSeries): number => s.candles.time.length;

/** How many footprint levels bar `i` has (0 without footprint). */
export function levelCount(s: ChartTableSeries, i: number): number {
  const offsets = s.footprint?.barIndexOffsets;
  if (offsets === undefined || i + 1 >= offsets.length) return 0;
  return (offsets[i + 1] ?? 0) - (offsets[i] ?? 0);
}

/** Bar `i`'s delta (ask − bid over its cells) in scaled integers, or null without footprint. */
function deltaScaled(s: ChartTableSeries, i: number): number | null {
  const fp = s.footprint;
  if (fp === undefined || i + 1 >= fp.barIndexOffsets.length) return null;
  let sum = 0;
  const end = fp.barIndexOffsets[i + 1] ?? 0;
  for (let k = fp.barIndexOffsets[i] ?? 0; k < end; k++) {
    sum +=
      qtyScaled(fp.cellAskVol[k] ?? 0, s.qtyDecimals) -
      qtyScaled(fp.cellBidVol[k] ?? 0, s.qtyDecimals);
  }
  return sum;
}

/** The running delta at each bar's close (the CVD the canvas draws), or null without footprint. */
export function cvdPrefix(s: ChartTableSeries): Float64Array | null {
  if (s.footprint === undefined) return null;
  const out = new Float64Array(barCount(s));
  let run = 0;
  for (let i = 0; i < out.length; i++) {
    run += deltaScaled(s, i) ?? 0;
    out[i] = run;
  }
  return out;
}

export const cvdAt = (
  s: ChartTableSeries,
  prefix: Float64Array | null,
  i: number,
): string | undefined =>
  prefix === null ? undefined : scaledToDecimal(prefix[i] ?? 0, s.qtyDecimals);

/** Bar `i` as decimal strings. */
export function barFields(s: ChartTableSeries, i: number): BarFields {
  const c = s.candles;
  const price = (ticks: number | undefined): string =>
    ticksToDecimal(ticks ?? 0, c.priceOrigin, c.tickSize, s.priceDecimals);
  const delta = deltaScaled(s, i);
  return {
    timeUs: c.time[i] ?? 0,
    open: price(c.open[i]),
    high: price(c.high[i]),
    low: price(c.low[i]),
    close: price(c.close[i]),
    volume: scaledToDecimal(qtyScaled(c.volume[i] ?? 0, s.qtyDecimals), s.qtyDecimals),
    delta: delta === null ? undefined : scaledToDecimal(delta, s.qtyDecimals),
  };
}

/**
 * The imbalance word for one level. PROPOSED stand-in until E18 owns the semantics (E11-D04 §6.1): a side is
 * stacked when its volume reaches `ratio` × the other side's.
 */
export function imbalanceOf(bid: number, ask: number, ratio: number): ImbalanceWord {
  if (ask > 0 && ask >= ratio * bid) return IMBALANCE_WORDS.ask;
  if (bid > 0 && bid >= ratio * ask) return IMBALANCE_WORDS.bid;
  return IMBALANCE_WORDS.none;
}

/** Bar `i`'s footprint levels, price descending (the `05` §6.3 default sort). */
export function levelsOf(s: ChartTableSeries, i: number): LevelFields[] {
  const fp = s.footprint;
  if (fp === undefined || levelCount(s, i) === 0) return [];
  const ratio = s.imbalanceRatio ?? 3;
  const q = s.qtyDecimals;
  const out: { ticks: number; row: LevelFields }[] = [];
  for (let k = fp.barIndexOffsets[i] ?? 0; k < (fp.barIndexOffsets[i + 1] ?? 0); k++) {
    const ticks = fp.cellPriceLevel[k] ?? 0;
    const bid = fp.cellBidVol[k] ?? 0;
    const ask = fp.cellAskVol[k] ?? 0;
    const row: LevelFields = {
      price: ticksToDecimal(ticks, fp.priceOrigin, fp.tickSize, s.priceDecimals),
      bid: scaledToDecimal(qtyScaled(bid, q), q),
      ask: scaledToDecimal(qtyScaled(ask, q), q),
      delta: scaledToDecimal(qtyScaled(ask, q) - qtyScaled(bid, q), q),
      imbalance: imbalanceOf(bid, ask, ratio),
    };
    out.push({ ticks, row });
  }
  return out.sort((a, b) => b.ticks - a.ticks).map((x) => x.row);
}
