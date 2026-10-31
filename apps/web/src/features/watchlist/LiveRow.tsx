/**
 * One SCR-100 row bound to its symbol's ticker store and the shared 1 Hz clock: CMP-161 WatchlistRow over CMP-049's row
 * contract. The row reads its own symbol's store, so a frame never re-renders the panel and a row repaints only on
 * the hub's coalesced writes of its symbol; ages and the funding countdown change on the clock's whole second.
 *
 * States (E08-D07 §4.2, D1, D2, D7, D20; one at a time): delisted (from the instrument); not live (outside the
 * subscription); initialising (in it, no value yet: "—", then "No data yet" after T1); live, stale from T1 = 5 s with
 * no fresh value and escalated at T2 = 15 s, or "Stale (server)" for a server-stale item. While Disconnected the panel
 * demotes every row and no row shows a chip (D29): precedence, never stacked.
 */
import { useCallback, useSyncExternalStore, type JSX } from "react";
import {
  WatchlistRow,
  type TableRowContext,
  type WatchlistFreshness,
  type WatchlistRowData,
  type WatchlistRowState,
} from "@candleviewer/ui";
import { formatUtcClock } from "../app-shell/clock";
import type { Instrument } from "../symbol-search/ranking";
import { COPY } from "./copy";
import { isDelisted } from "./instruments";
import { serverSkewMs, useSecondClock } from "./ticker/secondClock";
import type { TickerHub } from "./ticker/tickerHub";
import type { TickerEntry } from "./ticker/tickerStore";

/** E08-D07 D1: ticker cells go stale at T1 and escalate at T2. */
export const STALE_T1_MS = 5_000;
export const STALE_T2_MS = 15_000;

const noStore = (): (() => void) => () => undefined;

/** The instrument's price scale: `price_scale`, else the tick size's decimals. */
export function priceScaleOf(instrument: Instrument | undefined): number {
  if (instrument?.price_scale !== undefined) return instrument.price_scale;
  const decimals = instrument?.tick_size.split(".")[1];
  return decimals === undefined ? 2 : decimals.length;
}

/** A symbol's values as CMP-161 reads them; OI Δ has no 24 h baseline yet (D21; `/market/open-interest` is C-8's). */
export function rowDataOf(
  symbol: string,
  instrument: Instrument | undefined,
  entry: TickerEntry | undefined,
): WatchlistRowData {
  const v = entry?.values;
  const take = <K extends keyof WatchlistRowData>(
    key: K,
    value: WatchlistRowData[K] | undefined,
  ): Partial<WatchlistRowData> =>
    // A computed key types as a string index; `key` is one of the row's own keys and `value` its type.
    value === undefined ? {} : ({ [key]: value } as Partial<WatchlistRowData>);
  return {
    symbol,
    priceScale: priceScaleOf(instrument),
    ...take("lastPrice", v?.lastPrice),
    ...take("pctChange24h", v?.pctChange24h),
    ...take("turnover24h", v?.turnover24h),
    ...take("fundingRate", v?.fundingRate),
    ...take("nextFundingTimeMs", v?.nextFundingTimeMs),
    ...(v === undefined ? {} : { openInterestChangePct24h: null }),
    ...take("spreadBps", v?.spreadBps),
    ...take("volume24h", v?.volume24h),
    ...take("openInterestValue", v?.openInterestValue),
    ...take("markPrice", v?.markPrice),
    ...take("indexPrice", v?.indexPrice),
    ...take("bid1Price", v?.bid1Price),
    ...take("ask1Price", v?.ask1Price),
    ...take("high24h", v?.high24h),
    ...take("low24h", v?.low24h),
  };
}

/** Whether a live row is stale at `now` (client ms): T1 without a fresh value, or flagged by the server. */
export function isStale(entry: TickerEntry | undefined, now: number): boolean {
  if (entry === undefined) return false;
  return entry.values.serverStale || now - entry.freshAtMs >= STALE_T1_MS;
}

export interface LiveRowProps {
  readonly grid: TableRowContext;
  readonly symbol: string;
  readonly columns: readonly string[];
  readonly hub: TickerHub | null;
  readonly instrument: Instrument | undefined;
  /** In the hub's subscription. */
  readonly live: boolean;
  /** When the subscription that holds it began (the hub's clock): an initialising row's age. */
  readonly liveSince: number | null;
  /** Disconnected: no chip on any row; every value cell described by the panel status. */
  readonly down: boolean;
  readonly statusId: string;
  readonly active: boolean;
  readonly description?: string | undefined;
  /** A not-live row's why, at `now`, by its cause; none while the panel status says it (no WS client). */
  readonly notLiveDetail: (now: number) => string | undefined;
  readonly onActivate: () => void;
  readonly onMove: (direction: "up" | "down") => void;
  readonly moveReason: { readonly up?: string; readonly down?: string };
  readonly onRemove: () => void;
  readonly removeReason: string | undefined;
  readonly onCopy: (symbol: string) => void;
}

export function LiveRow(props: LiveRowProps): JSX.Element {
  const { symbol, hub, instrument, live, down } = props;
  const subscribe = useCallback(
    (listener: () => void) => hub?.store.subscribe(symbol, listener) ?? noStore(),
    [hub, symbol],
  );
  const read = useCallback(() => hub?.store.get(symbol), [hub, symbol]);
  const entry = useSyncExternalStore(subscribe, read, read);
  const now = useSecondClock();
  const delisted = isDelisted(instrument);
  const rowState: WatchlistRowState = delisted
    ? "delisted"
    : !live
      ? "not-live"
      : entry === undefined
        ? "initialising"
        : "live";

  let freshness: WatchlistFreshness | undefined;
  if (!down && rowState === "live" && entry !== undefined && isStale(entry, now)) {
    const ageMs = Math.max(0, now - entry.freshAtMs);
    freshness = {
      ticker: {
        state: "stale",
        ageMs,
        escalated: ageMs >= STALE_T2_MS,
        server: entry.values.serverStale,
        detail: COPY.lastUpdate(formatUtcClock(entry.values.tsMs)),
      },
    };
  } else if (
    !down &&
    rowState === "initialising" &&
    now - (props.liveSince ?? now) >= STALE_T1_MS
  ) {
    freshness = { ticker: { state: "stale" } }; // "No data yet" (D7)
  }

  const why = rowState === "not-live" ? props.notLiveDetail(now) : undefined;
  const optional = {
    ...(freshness === undefined ? {} : { freshness }),
    ...(props.description === undefined ? {} : { description: props.description }),
    ...(why === undefined ? {} : { notLiveDetail: why }),
    ...(down ? { describedBy: props.statusId } : {}),
    ...(props.removeReason === undefined ? {} : { removeReason: props.removeReason }),
  };
  return (
    <WatchlistRow
      grid={props.grid}
      row={rowDataOf(symbol, instrument, rowState === "live" ? entry : undefined)}
      columns={props.columns}
      rowState={rowState}
      nowMs={now + serverSkewMs()}
      active={props.active}
      onActivate={props.onActivate}
      onMove={props.onMove}
      moveReason={props.moveReason}
      onRemove={props.onRemove}
      onCopy={props.onCopy}
      {...optional}
    />
  );
}
