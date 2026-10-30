/**
 * What SCR-102 and SCR-041 report: E08-D05 §12.1's analytics on the app's seam (`cv:analytics` on `window`, as SCR-157
 * and SCR-159 report; nothing leaves the page), the query's length and never the query; and a commit's §6.2 sentence.
 * `chart.symbol_changed` is the chart's, when the new symbol paints (E12-S11).
 */
import { useEffect, useRef } from "react";
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";
import { useShellSelector } from "../../shell/useShellSelector.js";
import { announce, forget } from "../app-shell/announcer";
import { isDisconnected } from "../app-shell/shellMode";
import { commitSentence } from "./copy";
import type { IndexSnapshot, InstrumentIndex } from "./instrumentIndex";
import { normaliseQuery, rankSymbols, type SearchResult, type Tier } from "./ranking";
import { getSymbolSearchState, rememberSymbol, type SymbolTarget } from "./searchSession";
import { REST_MS } from "./symbolCheck";

export type SearchSurface = "scr-102" | "scr-041";
/** §12.1's `empty_state_shown` reasons. */
export type EmptyReason =
  "catalogue_loading" | "catalogue_load_failed" | "no_matches" | "scope_filtered";

const report = (detail: Readonly<Record<string, unknown>>): void => {
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
};

/**
 * `symbol.searched`, after the 300 ms rest; `catalogue_state` is the index's phase or `stale` (PROPOSED values; owner:
 * E08-D05 §12.1).
 */
function reportSearched(
  surface: SearchSurface,
  query: string,
  result: SearchResult,
  snapshot: IndexSnapshot,
): void {
  const ranked = result.kind === "results" ? result : null;
  report({
    name: "symbol.searched",
    surface,
    query_length: normaliseQuery(query).length,
    result_count: ranked?.total ?? 0,
    top_tier: ranked?.rows[0]?.tier ?? null,
    catalogue_state:
      snapshot.phase === "ready" && snapshot.staleSince !== null ? "stale" : snapshot.phase,
  });
}

/**
 * A commit or a menu action's option: its group, 1-based rank there, tier, and how (PROPOSED `action` values; owner:
 * E08-D05 §12.1).
 */
export interface Opened {
  readonly rank: number;
  readonly tier: Tier | null;
  readonly group: "recent" | "results";
  readonly input: "key" | "pointer";
  readonly action: "open" | "new-chart" | "info" | "forget";
}

export const reportOpened = (surface: SearchSurface, opened: Opened): void =>
  report({ name: "symbol.search_result_opened", surface, ...opened });

/**
 * §12.1 for one opening of a surface: `symbol.searched` once its query has rested 300 ms, once per query as normalised
 * (a trailing space is the same query), and `empty_state_shown` once per entry into a state (`shown`; StrictMode's
 * rehearsal says nothing twice). Both only while `open`: a surface may outlive its closing (CMP-017's exit fade, SCR-102's
 * mounted host), and a query abandoned inside its rest is never reported (CR-DD2-02).
 */
export function useSearchReports(
  surface: SearchSurface,
  index: InstrumentIndex,
  query: string,
  open: boolean,
  shown: EmptyReason | null,
): void {
  const searched = open ? normaliseQuery(query) : "";
  useEffect(() => {
    if (searched === "") return undefined;
    const timer = setTimeout(() => {
      const now = index.getSnapshot();
      const { recent } = getSymbolSearchState();
      reportSearched(surface, searched, rankSymbols(searched, { ...now, recent }), now);
    }, REST_MS);
    return () => clearTimeout(timer);
  }, [surface, index, searched]);
  const entered = open ? shown : null;
  const reported = useRef<EmptyReason | null>(null);
  useEffect(() => {
    if (entered !== null && reported.current !== entered)
      report({ name: "empty_state_shown", surface, reason: entered });
    reported.current = entered;
  }, [surface, entered]);
}

/**
 * E17-D01 Disconnected as the shell reads it (`isDisconnected`: a retry, offline, or connecting again after a loss):
 * the commit's resume clause and SCR-102's footer.
 */
export const useDisconnected = (): boolean =>
  useShellSelector((s) => isDisconnected(s.connection.kind, s.everLive));

/** The commit's one key in the shell announcer: forgotten before each commit, so each is said and none is kept. */
const COMMIT_KEY = "symbol-search:commit";

/**
 * After a commit to `into` (`null`: a new chart): Recent remembers it (D-9, one session list for both surfaces) and the
 * shell's polite region says §6.2's sentence at once, the user's own act (not after E17-D02 §11's 5 s region budget);
 * `lost` (`useDisconnected()`) adds its resume clause.
 */
export function sayCommit(symbol: string, into: SymbolTarget | null, lost: boolean): void {
  rememberSymbol(symbol);
  forget(COMMIT_KEY);
  announce("polite", commitSentence(symbol, into, lost), COMMIT_KEY);
}
