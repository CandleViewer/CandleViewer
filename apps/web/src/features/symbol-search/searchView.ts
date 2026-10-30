/**
 * SCR-102's view of one moment (E08-D05 §6.2): the ranked rows or the idle Recent group, the catalogue state that
 * replaces them, and what the one polite region says. Pure: the component passes the query, the snapshots and the
 * snapshot's arrival time. The symbol check's states (checking, no matches, the status rule) are PR C2's: until
 * then a query that ranks nothing lists nothing and says nothing, never "0 results".
 */
import type { FuzzyListItem } from "@candleviewer/ui";
import { COPY, statusText } from "./copy";
import type { IndexSnapshot, LoadFailure } from "./instrumentIndex";
import { rankSymbols, type IdleRow, type Instrument, type RankedRow } from "./ranking";

/** What stands in the list's place when nothing is listed. */
export type SearchEmpty =
  | { readonly kind: "first-run" }
  | { readonly kind: "failed"; readonly failure: LoadFailure | null; readonly waitS: number };

export interface SearchView {
  readonly items: readonly FuzzyListItem[];
  readonly recent: readonly FuzzyListItem[];
  readonly total: number;
  readonly loading: boolean;
  /** The polite region's sentence; `""` keeps it quiet, `undefined` lets CMP-160 say the count. */
  readonly message: string | undefined;
  readonly empty: SearchEmpty | null;
}

const waitS = (at: number | null, now: number): number =>
  Math.max(1, Math.round(((at ?? now) - now) / 1000));
const hint = (i: Instrument): string =>
  `${i.base_coin ?? i.symbol.slice(0, -4)} / ${i.quote_coin ?? "USDT"}`;

const rankedItem = (row: RankedRow): FuzzyListItem => ({
  id: row.instrument.symbol,
  label: row.instrument.symbol,
  matchRanges: row.ranges,
  hint: hint(row.instrument),
  ...(row.recent ? { tags: ["recent" as const] } : {}),
});

/** A Recent row; one that can't be opened is reached, never chosen, and says why (D-6). */
function idleItem({ symbol, instrument, openable }: IdleRow): FuzzyListItem {
  if (openable && instrument !== null) return { id: symbol, label: symbol, hint: hint(instrument) };
  const status = instrument?.status;
  const delisted = instrument?.delisted === true || status === "Closed" || status === "Delivering";
  const why = instrument === null ? "" : statusText(instrument);
  return {
    id: symbol,
    label: symbol,
    disabled: true,
    reason: `${COPY.notTrading(symbol)} ${why}`.trim(),
    ...(delisted ? { delisted, chip: { label: COPY.delisted, icon: "cancelled" as const } } : {}),
  };
}

export function searchView(
  query: string,
  snapshot: IndexSnapshot,
  recent: readonly string[],
  /** When the snapshot arrived (ms): its waits count from here, so no sentence ticks while typing. */
  now: number,
): SearchView {
  const quiet: SearchView = {
    items: [],
    recent: [],
    total: 0,
    loading: false,
    message: "",
    empty: null,
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
      items: result.rows.map(rankedItem),
      total: result.total,
      message: undefined,
    };
  if (result.kind !== "idle") return quiet; // "status" and "none" are PR C2's
  const rows = result.recent.map(idleItem);
  return {
    ...quiet,
    recent: rows,
    message: undefined,
    empty: rows.length > 0 ? null : { kind: "first-run" },
  };
}
