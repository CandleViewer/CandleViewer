/**
 * The one ranking rule for SCR-102, SCR-041 and the palette's symbol group (E08-D05 D-3, §4): pure and
 * synchronous, no I/O. A query is matched against the symbol and the base stripped of a leading
 * multiplier, both normalised once at load (`toEntry`); the quote is never matched. Only Trading
 * symbols rank; a query naming a known non-Trading symbol, with nothing ranked, is the status rule.
 * With no list in memory every query answers the index's phase, never "No matches" (§6.2).
 */
import type { generated } from "@candleviewer/protocol";

export type Instrument = generated.rest.components["schemas"]["Instrument"];
/** A matched span of the symbol, `[start, end)`: `symbol.slice(start, end)` is the text to bold. */
export type MatchRange = readonly [start: number, end: number];
export type Tier = 1 | 2 | 3 | 4 | 5;
/** The index's list: `loading` and `failed` have none in memory (E08-D05 §6.2). */
export type IndexPhase = "loading" | "failed" | "ready";

/** An instrument with its match fields, normalised once at load. */
export interface IndexEntry {
  readonly instrument: Instrument;
  readonly symbol: string;
  /** The symbol without its `USDT` quote ("1000PEPE"). */
  readonly base: string;
  /** The base without a leading power-of-ten multiplier ("PEPE"; "1INCH" unchanged). */
  readonly stripped: string;
}

export interface RankedRow {
  readonly instrument: Instrument;
  readonly tier: Tier;
  readonly ranges: readonly MatchRange[];
  readonly favourite: boolean;
  readonly recent: boolean;
}

/** An idle-group row: a delisted or unknown symbol is shown but not openable (D-6). */
export interface IdleRow {
  readonly symbol: string;
  readonly instrument: Instrument | null;
  readonly openable: boolean;
}

export type SearchResult =
  | {
      readonly kind: "idle";
      readonly recent: readonly IdleRow[];
      readonly favourites: readonly IdleRow[];
      /** "12 more favourites — type to search". */
      readonly moreFavourites: number;
    }
  /** At most 50 rows; `total` counts every match ("Showing 50 of 213"). */
  | { readonly kind: "results"; readonly rows: readonly RankedRow[]; readonly total: number }
  | { readonly kind: "status"; readonly instrument: Instrument }
  /** A list in memory, nothing ranked, nothing known: "No matches", and the check may run. */
  | { readonly kind: "none" }
  /** No list in memory: the Loading or Load failed state, never "No matches" (§6.2). */
  | { readonly kind: "loading" | "failed" };

export interface RankContext {
  readonly phase: IndexPhase;
  /** The Trading listing. */
  readonly entries: readonly IndexEntry[];
  /** Non-Trading symbols known this session: Recent, Favourite, the current value or checked. */
  readonly known?: readonly IndexEntry[];
  /** Newest first. */
  readonly recent?: readonly string[];
  readonly favourites?: readonly string[];
}

/** `22`'s `q` bound. */
export const QUERY_MAX = 32;
export const RESULT_CAP = 50;
const IDLE_CAP = 8;
const QUOTE = "USDT";
const DROPPED = /[\s/_-]/g;
const MULTIPLIER = /^1(0{1,6})(?=[A-Z])/;

/** Trim, upper-case, drop spaces and `/ - _` ("btc/usdt" reads `BTCUSDT`), cap at 32 characters. */
export const normaliseQuery = (raw: string): string =>
  raw.trim().toUpperCase().replace(DROPPED, "").slice(0, QUERY_MAX);

export function toEntry(instrument: Instrument): IndexEntry {
  const symbol = normaliseQuery(instrument.symbol);
  // The base is the symbol without its quote, whichever form `base_coin` takes (`1000PEPE` or `PEPE`,
  // D05 §4), so a match on it maps onto the symbol's characters.
  const base = symbol.slice(0, -QUOTE.length);
  return { instrument, symbol, base, stripped: base.replace(MULTIPLIER, "") };
}

interface Match {
  readonly tier: Tier;
  /** T5's window length; 0 elsewhere. */
  readonly span: number;
  /** T4's position, T5's start, in the stripped base; 0 elsewhere. */
  readonly at: number;
  readonly ranges: readonly MatchRange[];
}

/** T5: the shortest window of the stripped base holding the query in order, the earliest on a tie. */
function subsequence(stripped: string, query: string, offset: number): Match | null {
  let best: { start: number; end: number; picks: number[] } | null = null;
  const first = query.charAt(0);
  for (
    let start = stripped.indexOf(first);
    start >= 0;
    start = stripped.indexOf(first, start + 1)
  ) {
    const picks = [start];
    let end = start;
    for (let j = 1; j < query.length && end >= 0; j += 1) {
      end = stripped.indexOf(query.charAt(j), end + 1);
      picks.push(end);
    }
    if (end < 0) break; // a later start cannot complete either
    if (best === null || end - start < best.end - best.start) best = { start, end, picks };
  }
  if (best === null) return null;
  const ranges: [number, number][] = [];
  for (const pick of best.picks) {
    const tail = ranges[ranges.length - 1];
    if (tail !== undefined && tail[1] === offset + pick) tail[1] += 1;
    else ranges.push([offset + pick, offset + pick + 1]);
  }
  return { tier: 5, span: best.end - best.start + 1, at: best.start, ranges };
}

function match({ symbol, base, stripped }: IndexEntry, query: string): Match | null {
  const offset = base.length - stripped.length;
  const hit = (tier: Tier, from: number, at = 0): Match => ({
    tier,
    span: 0,
    at,
    ranges: [[from, from + query.length]],
  });
  if (query === symbol || query === base) return hit(1, 0);
  if (query === stripped) return hit(1, offset);
  if (symbol.startsWith(query)) return hit(2, 0);
  const at = stripped.indexOf(query);
  if (at === 0) return hit(3, offset);
  if (at > 0) return hit(4, offset + at, at);
  return query.length >= 3 ? subsequence(stripped, query, offset) : null;
}

interface Row extends Match {
  readonly entry: IndexEntry;
  readonly favourite: boolean;
  /** The position in Recent (newest first); Infinity when not recent. */
  readonly recentAt: number;
}

/** The tier and its own order, then favourite, recent (newer first), symbol in ASCII order. */
const compare = (a: Row, b: Row): number =>
  a.tier - b.tier ||
  a.span - b.span ||
  a.at - b.at ||
  Number(b.favourite) - Number(a.favourite) ||
  (a.recentAt === b.recentAt ? 0 : a.recentAt - b.recentAt) ||
  (a.entry.symbol < b.entry.symbol ? -1 : Number(a.entry.symbol > b.entry.symbol));

export function rankSymbols(rawQuery: string, ctx: RankContext): SearchResult {
  const { phase, entries, known = [], recent = [], favourites = [] } = ctx;
  if (phase !== "ready") return { kind: phase };
  const query = normaliseQuery(rawQuery);
  if (query === "") {
    const row = (symbol: string): IdleRow => {
      const instrument =
        (entries.find((e) => e.symbol === symbol) ?? known.find((e) => e.symbol === symbol))
          ?.instrument ?? null;
      return { symbol, instrument, openable: instrument?.status === "Trading" };
    };
    return {
      kind: "idle",
      recent: recent.slice(0, IDLE_CAP).map(row),
      favourites: favourites.slice(0, IDLE_CAP).map(row),
      moreFavourites: Math.max(0, favourites.length - IDLE_CAP),
    };
  }
  const rows: Row[] = [];
  const named: Row[] = [];
  for (const entry of [...entries, ...known]) {
    const found = match(entry, query);
    if (found === null) continue;
    const at = recent.indexOf(entry.symbol);
    const row: Row = {
      ...found,
      entry,
      favourite: favourites.includes(entry.symbol),
      recentAt: at < 0 ? Infinity : at,
    };
    if (entry.instrument.status === "Trading") rows.push(row);
    else if (found.tier === 1) named.push(row);
  }
  if (rows.length > 0) {
    rows.sort(compare);
    return {
      kind: "results",
      total: rows.length,
      rows: rows.slice(0, RESULT_CAP).map(({ entry, tier, ranges, favourite, recentAt }) => ({
        instrument: entry.instrument,
        tier,
        ranges,
        favourite,
        recent: recentAt !== Infinity,
      })),
    };
  }
  const status = named.sort(compare)[0];
  return status === undefined
    ? { kind: "none" }
    : { kind: "status", instrument: status.entry.instrument };
}
