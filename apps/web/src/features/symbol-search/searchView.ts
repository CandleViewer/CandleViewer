/**
 * SCR-102's view of one moment (E08-D05 §6.2): the ranked rows or the idle Recent group, the catalogue state that
 * replaces them, what the one polite region says, and the shared deck's case for a query that ranks nothing (never
 * "0 results"). Pure: the component passes the query, the snapshot, the session's caches and the snapshot's arrival.
 * Its row builders are SCR-041's too.
 */
import type { FuzzyListItem } from "@candleviewer/ui";
import { COPY, statusText } from "./copy";
import type { IndexSnapshot, LoadFailure } from "./instrumentIndex";
import { rankSymbols, type IdleRow, type Instrument, type RankedRow, type Tier } from "./ranking";
import { unmatchedOf, type Unmatched } from "./searchDeck";

/** What stands in the list's place when nothing is listed. */
export type SearchEmpty =
  | { readonly kind: "first-run" }
  | { readonly kind: "failed"; readonly failure: LoadFailure | null; readonly waitS: number };

export interface SearchView {
  readonly items: readonly FuzzyListItem[];
  /** Each ranked row's tier, in `items`' order (§12.1). */
  readonly tiers: readonly Tier[];
  readonly recent: readonly FuzzyListItem[];
  readonly total: number;
  readonly loading: boolean;
  /** The polite region's sentence; `""` keeps it quiet, `undefined` lets CMP-160 say the count. */
  readonly message: string | undefined;
  readonly empty: SearchEmpty | null;
  /** A query that ranks nothing with a list in memory: the shared deck's case. */
  readonly unmatched: Unmatched | null;
}

/** The session's caches the view reads: Recent and the current symbol, and the lookups with no usable answer. */
export interface SessionCaches {
  readonly remembered: readonly string[];
  readonly unchecked: readonly string[];
}

/** The whole seconds to `at` (a 503's next try), at least 1, counted from `now`: a snapshot's arrival, so none ticks. */
export const waitS = (at: number | null, now: number): number =>
  Math.max(1, Math.round(((at ?? now) - now) / 1000));
/** The base / quote column ("ETH / USDT"). */
export const hint = (i: Instrument): string =>
  `${i.base_coin ?? i.symbol.slice(0, -4)} / ${i.quote_coin ?? "USDT"}`;
/** §6.1's 24 h cells: "—" while the client holds no ticker (D-8); no words, so not in the option's name. */
const NO_TICKER = ["—", "—"] as const;

/** A ranked row (§4, §6.1), without SCR-102's 24 h cells (SCR-041 draws none, §7). */
export const rankedItem = (row: RankedRow): FuzzyListItem => ({
  id: row.instrument.symbol,
  label: row.instrument.symbol,
  matchRanges: row.ranges,
  hint: hint(row.instrument),
  ...(row.recent ? { tags: ["recent" as const] } : {}),
});

/**
 * A Recent row (D-6, §6.4; B04's ↺): one that can't be opened is reached, never chosen, and says why: its status, a
 * 404 from its session lookup (`unlisted`), or a lookup with no usable answer (`unchecked`).
 */
export function idleItem(
  { symbol, instrument, openable }: IdleRow,
  unlisted: readonly string[] = [],
  unchecked: readonly string[] = [],
): FuzzyListItem {
  const row = { id: symbol, label: symbol, group: "Recent", tags: ["recent" as const] };
  const known = instrument === null ? row : { ...row, hint: hint(instrument) };
  if (openable) return known;
  const status = instrument?.status;
  const delisted = instrument?.delisted === true || status === "Closed" || status === "Delivering";
  const reason =
    instrument !== null
      ? `${COPY.notTrading(symbol)} ${statusText(instrument)}`.trim()
      : unlisted.includes(symbol)
        ? COPY.gone(symbol)
        : unchecked.includes(symbol)
          ? COPY.unchecked(symbol)
          : COPY.notTrading(symbol);
  return {
    ...known,
    disabled: true,
    reason,
    ...(delisted ? { delisted, chip: { label: COPY.delisted, icon: "cancelled" as const } } : {}),
  };
}

/** Where `symbol` sits in `view` (§12.1): its group, its 1-based rank there and a ranked row's tier. */
export function placeOf(
  view: SearchView,
  symbol: string,
): { readonly rank: number; readonly tier: Tier | null; readonly group: "recent" | "results" } {
  const at = view.items.findIndex((item) => item.id === symbol);
  if (at >= 0) return { rank: at + 1, tier: view.tiers[at] ?? null, group: "results" };
  return {
    rank: view.recent.findIndex((item) => item.id === symbol) + 1,
    tier: null,
    group: "recent",
  };
}

export function searchView(
  query: string,
  snapshot: IndexSnapshot,
  recent: readonly string[],
  /** When the snapshot arrived (ms): its waits count from here, so no sentence ticks while typing. */
  now: number,
  caches: SessionCaches,
): SearchView {
  const quiet: SearchView = {
    items: [],
    tiers: [],
    recent: [],
    total: 0,
    loading: false,
    message: "",
    empty: null,
    unmatched: null,
  };
  const result = rankSymbols(query, { ...snapshot, recent });
  const wait = waitS(snapshot.retryAt, now);
  if (result.kind === "loading")
    return {
      ...quiet,
      loading: true,
      message: snapshot.retryAt === null ? COPY.loading : COPY.loadingRetry(wait),
    };
  if (result.kind === "failed")
    // its alert speaks, once
    return { ...quiet, empty: { kind: "failed", failure: snapshot.failure, waitS: wait } };
  if (result.kind === "results")
    return {
      ...quiet,
      items: result.rows.map((row) => ({ ...rankedItem(row), values: NO_TICKER })),
      tiers: result.rows.map((row) => row.tier),
      total: result.total,
      message: undefined,
    };
  if (result.kind !== "idle")
    return {
      ...quiet,
      unmatched: unmatchedOf(query, result, snapshot.unlisted, caches.remembered),
    };
  const rows = result.recent.map((row) => {
    const item = idleItem(row, snapshot.unlisted, caches.unchecked);
    return item.disabled === true ? item : { ...item, values: NO_TICKER };
  });
  return {
    ...quiet,
    recent: rows,
    message: undefined,
    empty: rows.length > 0 ? null : { kind: "first-run" },
  };
}
