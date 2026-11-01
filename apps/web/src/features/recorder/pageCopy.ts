/**
 * SCR-140's page and grid strings that `copy.ts` (the model's) does not hold, each with its source.
 * E16-D02's own words are verbatim; a string marked PROPOSED is this story's, for E16-D02's owner at
 * its next text touch (E16-D06 §16.4: a code with no named sentence is the consuming story's to
 * build). Nothing here is composed from a server `message` or `detail` (E16-D06 §20.3).
 */
import type { generated } from "@candleviewer/protocol";

type StreamKind = generated.rest.components["schemas"]["StreamKind"];

/** The deck rows this page shows that `copy.ts` does not carry, under the deck's keys (E16-D04 §14). */
export const PAGE_DECK = {
  "storage.job.refused.running": [
    "A {verb} is already running.",
    "A compaction is already running.",
  ],
} as const satisfies Readonly<Record<string, readonly string[]>>;

export const PAGE_TEXT = {
  /** D02 §10.2: the grid's name. */
  grid: "Recorded symbols",
  /** D02 §1: the search box. */
  search: "Filter symbols",
  /** D02 §1: the disk card's entry points to SCR-141 and SCR-142 (BQ-11: shown once registered). */
  retentionPolicy: "Retention policy",
  storageDetails: "Storage details",
  /** D02 §10.2: the disk bar's name. */
  budget: "Recording budget",
  /** D02 §10.2: the gap table's columns. */
  gapColumns: { start: "Start", end: "End", duration: "Duration", reason: "Reason" },
  /** D02 §5.1, the Why? popover, per reason (the chart and position variants are D02's words). */
  why: {
    chart:
      "{symbol}'s chart has been open since {open} UTC; recording started {dwell} later, at {start}. It stops {grace} after the last {symbol} chart closes.",
    position:
      "{symbol} has an open position (since {start} UTC); recording continues while it is open and stops {grace} after the last reason ends.",
    /** PROPOSED (owner E16-D02): §5.1 names the rule or alert, which no contract field carries. */
    rule: "A rule depends on {symbol}; recording continues while it does and stops {grace} after the last reason ends.",
    alert:
      "An alert depends on {symbol}; recording continues while it does and stops {grace} after the last reason ends.",
    kept: "Data is kept for {days} days.",
    /** PROPOSED (owner E16-D02): §5.1's sentence for a pinned row. */
    keptForever: "Data is kept forever.",
  },
  /**
   * PROPOSED (owner E16-D02; E16-D06 §16.4 rows 1, 4, 6, 7, 13 and 15): the generic T4, the outcome
   * and "the server refused it", the code token after it in parentheses.
   */
  refused: {
    add: "Not started: the server refused it.",
    stop: "Not stopped: the server refused it.",
    compact: "Not started: the server refused it.",
    /** PROPOSED (owner E16-D02; E16-D06 §16.4 row 10): a job's poll refused; its last line stands. */
    poll: "Status not updated: the server refused it.",
  },
  /** No answer: the app's existing words (the change-password screen's, E09-D06). */
  unreachable: "Cannot reach the server. Try again.",
  /**
   * PROPOSED (owner E16-D02; D-5309-02, C-5309-06): a settled search or a chip change, said once when the rows shown
   * changed ("1 of 5 symbols.").
   */
  shownOf: "{shown} of {total} symbols.",
  shownOfOne: "{shown} of 1 symbol.",
  /**
   * None shown: CMP-026 `filtered-empty` in the deck's filter class (E16-D05 section 14's `classes.filter.heading`,
   * `.cause` and `.cta`, PROPOSED exemplars there; a test holds them to the deck), said once as its
   * `empty.announce.enter` puts it, "{heading} {cause}", the heading closed with a full stop.
   */
  noMatch: "No symbols match these filters",
  noMatchCause: "Widen or clear a filter to see symbols.",
  clearFilters: "Clear filters",
  /** PROPOSED (owner E16-D02; D-5309-11): the purge banner's CMP-023 bar, named for what it measures. */
  purgeBar: "Purge of {symbol}",
} as const;

/** The gap table's reason words: E16-D02 §2 where it gives one, else E16-D05 §2's short form. */
export const GAP_REASONS: Readonly<Record<string, string>> = {
  backpressure_drop: "write gate (disk full)",
  seq_jump: "sequence jump",
  ws_disconnect: "connection lost",
  backend_restart: "CandleViewer restarted",
  exchange_outage: "exchange outage",
  retention_purge: "removed by retention",
};
/** D02 §2: a reason this build does not know reads as a gap (the enum is open-ended, C-6.3). */
export const UNKNOWN_GAP = "gap";

/** D02 §6.1's streams, its words in its order: the first four are the add's defaults (`22`). */
export const STREAM_LABELS: Readonly<Record<StreamKind, string>> = {
  trades: "Trades",
  orderbook_delta: "Order-book deltas",
  tickers: "Tickers",
  liquidations: "Liquidations",
  klines: "Klines",
  orderbook_snapshot: "Order-book snapshots",
  open_interest: "Open interest",
  funding: "Funding",
};

/**
 * The FilterBar's fields (BQ-10: Reason, State, Pinned, Needs attention, each with a value submenu;
 * D02 §8.3's "Reduce depth" filters by Depth). Field names are D02 §1's; the values are PROPOSED
 * (owner E16-D02), the state values the leading words of D02 §4.1's state words.
 */
export const FILTER_TEXT = {
  reason: { label: "Reason", values: { manual: "Manual", auto: "Auto" } },
  state: {
    label: "State",
    values: {
      recording: "Recording",
      starting: "Starting",
      degraded: "Degraded",
      gated: "Gated",
      refused: "Not recording",
      silent: "No writes",
      error: "Error",
      stopping: "Stopping",
      stopped: "Stopped",
    },
  },
  pinned: { label: "Pinned", values: { yes: "Yes", no: "No" } },
  attention: { label: "Needs attention", values: { yes: "Yes", no: "No" } },
  depth: { label: "Depth", values: { "1": "1", "50": "50", "200": "200", "500": "500" } },
} as const;
