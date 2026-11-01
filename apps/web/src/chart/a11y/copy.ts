/**
 * SCR-045's words (E47-S01, #1316). PROPOSED pending E47-D06 (#1305): every string here is taken from
 * `05-accessibility-standard.md` §6 or E11-D04 §19's copy deck, never frozen; D06 confirms or replaces them. The one
 * string with no deck source, the expander column's header, is marked as such.
 */

export const VIEW_GROUP = "Chart view";
export const VIEW_CHART = "Chart";
export const VIEW_TABLE = "Table";
/** The table toggle's hint; the key is the keymap's default (`chart.table_toggle`). */
export const VIEW_TABLE_HINT = "Table view — Alt+T";

/** PROPOSED with no deck source (E11-D04 §5.1 draws the expander column without a header). */
export const EXPANDER_HEADER = "levels";
export const BAR_HEADERS = [
  "time",
  "open",
  "high",
  "low",
  "close",
  "volume",
  "delta",
  "CVD",
] as const;
export const LEVEL_HEADERS = ["price", "bid", "ask", "delta", "imbalance"] as const;

export const IMBALANCE_WORDS = { bid: "Bid-stacked", ask: "Ask-stacked", none: "—" } as const;
export const NOT_AVAILABLE = "—";
export const NO_FOOTPRINT = "No footprint for this bar";

const rows = (n: number): string => `${n.toLocaleString("en-GB")} ${n === 1 ? "row" : "rows"}`;

export const expandName = (levels: number): string => `Expand ${levels} levels`;
export const collapseName = (levels: number): string => `Collapse ${levels} levels`;
export const levelsCaption = (levels: number, high: string, low: string): string =>
  `${levels} price levels, ${high} to ${low}`;
export const tableCaption = (title: string, bars: number): string =>
  `${title} — ${bars.toLocaleString("en-GB")} bars loaded`;

/** The table's polite lines, once per user action (E11-D04 §17.3). */
export const SAY = {
  chart: "Chart",
  tableRow: (row: number, total: number): string =>
    `Data table, row ${row.toLocaleString("en-GB")} of ${total.toLocaleString("en-GB")}`,
  expanded: (levels: number): string => `Expanded, ${levels} levels`,
  collapsed: "Collapsed",
  selected: (n: number): string => `Selected, ${rows(n)}`,
  deselected: "Deselected",
  copied: (n: number, columns: number): string => `Copied ${rows(n)}, ${columns} columns as TSV`,
  copiedCapped: (cap: number, n: number): string =>
    `Copied the first ${cap.toLocaleString("en-GB")} of ${n.toLocaleString("en-GB")} selected rows as TSV`,
} as const;
