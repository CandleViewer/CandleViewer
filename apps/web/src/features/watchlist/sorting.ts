/**
 * SCR-100's sort (E08-D07 D5, §4.1 "Sort"): a pane view setting, the list's manual order by default. Symbol sorts A–Z;
 * the live columns by their ticker value, a row with none last whichever the direction, ties in manual order. Pure: the
 * caller passes each symbol's entry. A live-column sort re-ranks at most every `LIVE_SORT_MS` and holds while the
 * pointer or focus is in the grid or its footer (the panel's).
 */
import type { TableSort } from "@candleviewer/ui";
import type { TickerEntry } from "./ticker/tickerStore";

export const LIVE_SORT_MS = 2_000;

/** Columns whose order comes from the ticker (the ticker group, and OI Δ). */
export const isLiveColumn = (columnId: string): boolean =>
  columnId !== "symbol" && columnId !== "rec" && columnId !== "status";

/** The value a live column sorts by, or `undefined` when the row has none. OI Δ has no baseline yet (D21, C-8). */
export function sortValue(columnId: string, entry: TickerEntry | undefined): number | undefined {
  const v = entry?.values;
  if (v === undefined) return undefined;
  switch (columnId) {
    case "last":
      return v.lastPrice;
    case "chg_24h_pct":
      return v.pctChange24h;
    case "turnover_24h":
      return v.turnover24h;
    case "funding_rate":
      return v.fundingRate;
    case "next_funding":
      return v.nextFundingTimeMs;
    case "spread_bps":
      return v.spreadBps;
    case "volume_24h":
      return v.volume24h;
    case "open_interest_value":
      return v.openInterestValue;
    case "mark_price":
      return v.markPrice;
    case "index_price":
      return v.indexPrice;
    case "bid1_price":
      return v.bid1Price;
    case "ask1_price":
      return v.ask1Price;
    case "high_24h":
      return v.high24h;
    case "low_24h":
      return v.low24h;
    default:
      return undefined;
  }
}

/** `symbols` in the order `sort` gives (the manual order without one). */
export function ranked(
  symbols: readonly string[],
  sort: TableSort | null,
  read: (symbol: string) => TickerEntry | undefined,
): readonly string[] {
  if (sort === null || sort.columnId === "rec" || sort.columnId === "status") return symbols;
  const sign = sort.direction === "ascending" ? 1 : -1;
  const at = new Map(symbols.map((symbol, i) => [symbol, i]));
  const tie = (a: string, b: string): number => (at.get(a) ?? 0) - (at.get(b) ?? 0);
  if (sort.columnId === "symbol")
    return [...symbols].sort((a, b) => sign * (a < b ? -1 : a > b ? 1 : 0) || tie(a, b));
  const value = new Map(symbols.map((symbol) => [symbol, sortValue(sort.columnId, read(symbol))]));
  return [...symbols].sort((a, b) => {
    const x = value.get(a);
    const y = value.get(b);
    if (x === undefined || y === undefined) return x === y ? tie(a, b) : x === undefined ? 1 : -1;
    return sign * (x - y) || tie(a, b);
  });
}

/** The pane setting's form, `column:direction` (`watchlist_sort`, a string ≤ 256, `22`). */
export const encodeSort = (sort: TableSort | null): string =>
  sort === null ? "" : `${sort.columnId}:${sort.direction}`;

export function decodeSort(text: string | undefined): TableSort | null {
  const [columnId, direction] = (text ?? "").split(":");
  if (columnId === undefined || columnId === "") return null;
  return direction === "ascending" || direction === "descending" ? { columnId, direction } : null;
}
