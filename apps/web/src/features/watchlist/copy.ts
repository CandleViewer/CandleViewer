/**
 * SCR-100's words (E08-D07 §4.2, §4.5, §4.6, §6.7, D10, D23, D36): verbatim where the spec quotes a source, else its
 * proposed copy. A string the spec does not give is marked PROPOSED here and carried as a G-row on #4702. The
 * reason vocabulary is E09-D09 §3's: `rbac.permission` with `workspaces:write`'s §3.2 verb, "save workspaces", until
 * the A10 amendment narrows it to "change watchlists" (E08-D07 §6.7).
 */
import { formatRbacReason } from "@candleviewer/ui";
import { formatAge } from "../../lib/ws/state/connectionRegion";
import { COPY as SEARCH_COPY } from "../symbol-search/copy";

/** `22` `WatchlistInput.symbols` `maxItems: 200` (E08-D07 §1). */
export const LIST_CAP = 200;
/** From here the footer's count reads against the cap (E08-D07 D10). */
export const NEAR_CAP = 180;

const symbolsWord = (n: number): string => (n === 1 ? "1 symbol" : `${n} symbols`);
const WRITE_REASON = formatRbacReason("rbac.permission", { verb: "save workspaces" });

export const COPY = {
  /** The R-111 page's heading: the panel header's "Watchlist:" (E08-D07 §4.1). */
  title: "Watchlist",
  /** The panel's region, "Watchlist Majors" (E08-D07 §6.3, proposed). */
  region: (name: string): string => `Watchlist ${name}`,
  /** The list tabs' name. PROPOSED. */
  tablist: "Watchlists",
  /** The grid's caption: "Watchlist Majors, 12 symbols, manual order" (E08-D07 §4.2 Live), "filtered", "paused". */
  caption: (name: string, count: number, order: string, filtered: boolean, paused: boolean) =>
    `Watchlist ${name}, ${symbolsWord(count)}, ${order}${filtered ? ", filtered" : ""}${paused ? ", paused" : ""}`,
  manualOrder: "manual order",
  /** PROPOSED: the order a sorted caption names. */
  sortedBy: (header: string, direction: "ascending" | "descending"): string =>
    `sorted by ${header}, ${direction}`,
  /** The footer's count (E08-D07 §4.6, D10): "12 symbols", "120 symbols · 39 live", "187 / 200 symbols · 39 live". */
  count: (total: number, live: number): string => {
    const head = total >= NEAR_CAP ? `${total} / ${LIST_CAP} symbols` : symbolsWord(total);
    return total === 0 || live >= total ? head : `${head} · ${live} live`;
  },
  /** D4 (E08-D03's per-panel copy); with no data this session, the first part alone (PROPOSED). */
  disconnected: (ageMs: number | null): string =>
    ageMs === null ? "Disconnected" : `Disconnected — last data ${formatAge(ageMs)} ago`,
  /** §4.6, after a refused `sub` (proposed): the wait as it stands, in whole seconds counting down to 1. */
  paused: (waitMs: number): string =>
    `Live prices paused — retrying in ${Math.max(1, Math.floor(waitMs / 1000))} s`,
  /** §4.2 Not live, the budget short; the other panels' count only when they hold some (PROPOSED cut). */
  notLiveShort: (others: number): string =>
    others > 0
      ? `At most 40 symbols are live on one connection; other panels use ${others}.`
      : "At most 40 symbols are live on one connection.",
  /** §4.2 Not live, while a change waits for the rebuild share. */
  notLiveWait: (waitMs: number): string =>
    `This row goes live in ${Math.max(1, Math.ceil(waitMs / 1000))} s; the live rows change at most 4 times a minute.`,
  /** §4.2 Stale row, T1 (proposed): "Last update 10:31:02 UTC". */
  lastUpdate: (utc: string): string => `Last update ${utc}`,
  /** §4.5's episode summary: up to three names, then "and N more". */
  staleSummary: (symbols: readonly string[]): string => {
    const names = symbols.slice(0, 3).join(", ");
    const more = symbols.length > 3 ? ` and ${symbols.length - 3} more` : "";
    const head =
      symbols.length === 1 ? "1 watchlist symbol" : `${symbols.length} watchlist symbols`;
    return `${head} stale: ${names}${more}.`;
  },
  liveAgain: "Watchlist prices live again.",
  /** D23 / §4.2 Empty list and No lists. */
  emptyTitle: "No symbols on this watchlist",
  emptyBody: (name: string): string => `You haven't added any symbols to ${name} yet.`,
  emptyAction: "Add symbols to watch",
  importList: "Import a list",
  noListsTitle: "No watchlists yet",
  /** §4.2 Viewer: no list and no `workspaces:write`. */
  noListsReadOnly: "No watchlists",
  createList: "Create watchlist",
  /** §4.2 Errors. */
  loadFailed: "Watchlists could not be loaded.",
  /** E08-S09's index failed (no symbol is known to trade, so none is live): E08-D05 §6.2's Load failed, verbatim. */
  indexFailed: SEARCH_COPY.failed,
  retry: "Retry",
  saveFailed: (name: string): string => `Could not save ${name}. Your last change was undone.`,
  /** §4.3 Save failed's conflict (E08-T07's version field). */
  conflict: (name: string): string => `${name} changed in another window.`,
  reload: (name: string): string => `Reload ${name}`,
  /** E09-D09 `inflight.not_sent`: a save refused 403. */
  notSent: "Not sent — your access changed.",
  /** §4.5, §6.2. */
  removed: (symbol: string): string => `Removed ${symbol}. Undo is in the footer.`,
  undo: (count: number): string => (count > 1 ? `Undo ${count} removals` : "Undo"),
  moved: (symbol: string, position: number, total: number): string =>
    `${symbol} moved to position ${position} of ${total}.`,
  /** §6.7's state reasons. */
  first: "Already first.",
  last: "Already last.",
  reorderSorted: "Switch to manual order to reorder.",
  reorderFiltered: "Clear the filter to reorder.",
  capFull: "Watching 200 symbols — remove some to add more",
  symbolFixed: "The symbol column is always shown.",
  sortNeedsLive: "Live sort needs every symbol live.",
  delisted: "Delisted by the exchange",
  /** E09-D09 `rbac.permission` and `notice.panel_read_only` (§2.2: one notice, many pointers). */
  writeReason: WRITE_REASON,
  readOnly: `Read-only — ${WRITE_REASON.charAt(0).toLowerCase()}${WRITE_REASON.slice(1)}`,
  /** §4.1's footer. */
  addSymbol: "Add symbol",
  columns: "Columns",
  sort: (header: string | null): string => `Sort: ${header ?? "Manual"}`,
  sortPaused: " · paused",
  resort: "Re-sort",
  /** PROPOSED: the Sort menu's first item. */
  sortManual: "Manual order",
  filter: "Filter symbols",
  showing: (shown: number, total: number): string => `Showing ${shown} of ${total} symbols`,
  noMatch: (name: string, query: string): string => `No symbol on ${name} matches '${query}'.`,
  /** D36's add popover. */
  addTo: (name: string): string => `Add to ${name}`,
  /** §4.2 Adding: SCR-101's paste on this list (proposed). */
  pasteSeveral: "Paste several…",
  onList: (name: string): string => `On ${name}`,
  added: (symbol: string, name: string): string => `Added ${symbol} to ${name}.`,
  alreadyOn: (symbol: string, name: string): string => `${symbol} is already on ${name}.`,
  /** §4.2 Row menu (the record items are E16-S02's). */
  openInNewChart: "Open in new chart",
  sendToPanel: "Send to panel",
  copySymbol: "Copy symbol",
  moveUp: "Move up",
  moveDown: "Move down",
  removeFrom: (name: string): string => `Remove from ${name}`,
  /** The active row's description (§4.2 Live, proposed): its sync group. */
  showsIn: (group: string): string => `Shows in group ${group}`,
} as const;
