/**
 * A CV `ticker` item (`23-ws-protocol.md` §14.8; the generated `TickerSymbolTicker`) as SCR-100 draws it (E08-D07 §4.1,
 * D9): the wire's decimal strings read as numbers for display only (never an order value), percentages in points (the
 * wire fraction × 100), the spread in bps from the same frame's bid and ask. A value the item lacks stays absent, so
 * the cell reads "—"; an item whose last price is not a finite number is refused whole.
 */
import type { generated } from "@candleviewer/protocol";

export type TickerBody = generated.ws.TickerSymbolTicker;
export type TickerItem = TickerBody["tickers"][number];

/** One symbol's ticker values, as numbers. */
export interface TickerValues {
  readonly symbol: string;
  readonly lastPrice: number;
  /** `price_change_pct_24h` × 100. */
  readonly pctChange24h?: number;
  readonly turnover24h?: number;
  /** `funding_rate` × 100. */
  readonly fundingRate?: number;
  readonly nextFundingTimeMs?: number;
  /** (ask − bid) ÷ mid × 10 000. */
  readonly spreadBps?: number;
  readonly volume24h?: number;
  readonly openInterest?: number;
  readonly openInterestValue?: number;
  readonly markPrice?: number;
  readonly indexPrice?: number;
  readonly bid1Price?: number;
  readonly ask1Price?: number;
  readonly high24h?: number;
  readonly low24h?: number;
  /** The merged state's event time (exchange ms): the stale chip's "Last update 10:31:02 UTC". */
  readonly tsMs: number;
  /** The per-item `stale` (§14.8): "Stale (server)" (E08-D07 D1). */
  readonly serverStale: boolean;
}

/** A decimal string as a finite number, else `undefined`. */
const num = (text: string | undefined): number | undefined => {
  if (text === undefined || text.trim() === "") return undefined;
  const value = Number(text);
  return Number.isFinite(value) ? value : undefined;
};

/** `{ [key]: value }` when the value is present, `{}` otherwise (exact optional properties). */
const opt = <K extends string>(key: K, value: number | undefined): Partial<Record<K, number>> =>
  value === undefined ? {} : ({ [key]: value } as Record<K, number>); // a computed key types as a string index

const points = (fraction: number | undefined): number | undefined =>
  fraction === undefined ? undefined : fraction * 100;

/** D9: the spread in bps from one frame's top of book; none without both sides or with a crossed one. */
function spreadBps(bid: number | undefined, ask: number | undefined): number | undefined {
  if (bid === undefined || ask === undefined || bid <= 0 || ask < bid) return undefined;
  const mid = (bid + ask) / 2;
  return ((ask - bid) / mid) * 10_000;
}

export function tickerValues(item: TickerItem): TickerValues | null {
  const lastPrice = num(item.last_price);
  if (lastPrice === undefined || !Number.isFinite(item.ts_ms)) return null;
  const bid = num(item.bid1_price);
  const ask = num(item.ask1_price);
  return {
    symbol: item.symbol,
    lastPrice,
    ...opt("pctChange24h", points(num(item.price_change_pct_24h))),
    ...opt("turnover24h", num(item.turnover_24h)),
    ...opt("fundingRate", points(num(item.funding_rate))),
    ...opt("nextFundingTimeMs", item.next_funding_time_ms),
    ...opt("spreadBps", spreadBps(bid, ask)),
    ...opt("volume24h", num(item.volume_24h)),
    ...opt("openInterest", num(item.open_interest)),
    ...opt("openInterestValue", num(item.open_interest_value)),
    ...opt("markPrice", num(item.mark_price)),
    ...opt("indexPrice", num(item.index_price)),
    ...opt("bid1Price", bid),
    ...opt("ask1Price", ask),
    ...opt("high24h", num(item.high_24h)),
    ...opt("low24h", num(item.low_24h)),
    tsMs: item.ts_ms,
    serverStale: item.stale === true,
  };
}

const isRecord = (value: unknown): value is Readonly<Record<string, unknown>> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** The fields a ticker item needs before it is read: a symbol, a last price and its time. */
const isItem = (value: unknown): value is TickerItem =>
  isRecord(value) &&
  typeof value["symbol"] === "string" &&
  typeof value["last_price"] === "string" &&
  typeof value["ts_ms"] === "number";

/**
 * A frame body's items (`{ tickers: [...] }`), each one checked for the fields read first; anything that is no
 * TickerUpdate gives none. The WS client validated the frame; this is the consumer's own guard at its seam.
 */
export function tickerItemsOf(body: unknown): readonly TickerItem[] {
  if (!isRecord(body) || !Array.isArray(body["tickers"])) return [];
  return body["tickers"].filter(isItem);
}
