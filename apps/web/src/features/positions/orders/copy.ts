/**
 * The Working-orders tab's words that the E29-D06 deck does not key (E29-S02 #912). Two kinds:
 *
 * - **Merged design words**, each cited to its line (a test finds it there): E29-D01 D2's state
 *   words (D01:177–191), E29-D02 §6.1's column words (D02:263–274), the group rows' environment
 *   words (D02:238, :207), D01 D1's purposes for the five intents D02 does not draw (D01:153) and
 *   E30-D02's trigger-by label "Index" (E30-D02:243) and tab labels "Iceberg", "Chase" and "Scaled"
 *   (E30-D02:244). Like `../copy.ts`'s `D02_TEXT`, a string changes only through its owner (D06
 *   §6: no string invented).
 * - **PROPOSED keys** (BQ-9): words no merged design draws, routed to E29-D03's copy owner (G-W3)
 *   as #911's BQ-15 routed its own, and listed in the PR body for the ledger row. A test holds each
 *   one out of the deck, so the deck adopting a key fails it until the entry moves to `DECK`.
 *
 * The deck's own Working-orders keys (S-12, S-13, S-35, S-36) are in `../copy.ts`. Nothing here, or
 * there, carries the exchange's text: no `ret_msg`, `retCode` or server `detail`, and no "already
 * filled" (BQ-2, BQ-3).
 */
import { bindEntry, type DeckEntry } from "../copy";

/** A merged design string and the line it is drawn at ("D01:177", "D02:269"). */
export interface CitedText {
  readonly string: string;
  readonly source: string;
}

/** E29-D01 D2: the B1 `lifecycle` state's word. `draft` and `validated` are never shown. */
export const STATE_WORDS = {
  submitting: { string: "Sending", source: "D01:177" },
  submitted: { string: "Working", source: "D01:178" },
  triggered: { string: "Triggered", source: "D01:179" },
  partially_filled: { string: "Partial", source: "D01:180" },
  cancel_pending: { string: "Cancelling", source: "D01:181" },
  amend_pending: { string: "Amending", source: "D01:182" },
  unknown: { string: "Unknown — checking", source: "D01:183" },
  quarantined: { string: "Quarantined", source: "D01:184" },
  held: { string: "Held — owner review", source: "D01:185" },
  untracked: { string: "Untracked — not placed by CandleViewer", source: "D01:186" },
  filled: { string: "Filled", source: "D01:187" },
  cancelled: { string: "Cancelled", source: "D01:188" },
  rejected: { string: "Rejected", source: "D01:189" },
  expired: { string: "Expired", source: "D01:190" },
  killed: { string: "Killed (kill switch)", source: "D01:191" },
} as const satisfies Readonly<Record<string, CitedText>>;

/** E29-D02 §6.1's words for the State cell's null and the other columns. */
export const ORDER_TEXT = {
  /** A null or unmapped state reads as live (`23` §15.1). */
  notReported: { string: "Working — state not reported", source: "D02:274" },
  /** The side's word and its glyph, apart (D02:263 draws "▲ Buy"): the glyph is drawn, never read. */
  buy: { string: "Buy", source: "D02:263" },
  sell: { string: "Sell", source: "D02:263" },
  buyGlyph: { string: "▲", source: "D02:263" },
  sellGlyph: { string: "▼", source: "D02:263" },
  limit: { string: "Limit", source: "D02:264" },
  market: { string: "Market", source: "D02:264" },
  /** The Price column of a market order (D02:268: "a market order reads "Market""). */
  marketPrice: { string: "Market", source: "D02:268" },
  lastPrice: { string: "Last", source: "D02:269" },
  markPrice: { string: "Mark", source: "D02:269" },
  /** E30-D06 `ticket.order.label.trigger_by.index` (by reference, owner E30-D02): the drawn label. */
  indexPrice: { string: "Index", source: "E30-D02:243" },
  rises: { string: "rises to", source: "D02:269" },
  falls: { string: "falls to", source: "D02:269" },
  postOnly: { string: "Post-only", source: "D02:270" },
  reduceOnly: { string: "Reduce-only", source: "D02:271" },
  closeOnTrigger: { string: "Close on trigger", source: "D02:271" },
  /** The "—" of a column with nothing to show (D02:271: ""—" when none"). */
  none: { string: "—", source: "D02:271" },
  bracket: { string: "Bracket", source: "D02:273" },
  twap: { string: "TWAP", source: "D02:273" },
  /**
   * E30-D06 `ticket.order.label.tab.iceberg`, `.chase` and `.scaled` (by reference, owner E30-D02,
   * drawn at E30-D02:244): the algo's own name. `oco` has none: it is PROPOSED below.
   */
  iceberg: { string: "Iceberg", source: "E30-D02:244" },
  chase: { string: "Chase", source: "E30-D02:244" },
  scaled: { string: "Scaled", source: "E30-D02:244" },
  groupLeg: { string: "Group leg", source: "D02:273" },
  /** The account group row's environment (D02:238 "Main · LIVE"; D02:207 "Main · DEMO", §5.2). */
  live: { string: "LIVE", source: "D02:238" },
  demo: { string: "DEMO", source: "D02:207" },
} as const satisfies Readonly<Record<string, CitedText>>;

/** The Age column's units, as D02:272 writes "38 s", "4 m" and "1 h 12 m". */
export const AGE_UNITS = {
  seconds: { string: "s", source: "D02:272" },
  minutes: { string: "m", source: "D02:272" },
  hours: { string: "h", source: "D02:272" },
} as const satisfies Readonly<Record<string, CitedText>>;

/**
 * E29-D02 D-19's purpose, after the order type ("Limit · Take profit"): D02:264 draws three; the
 * other five are D01 D1's names of `intent`'s values (D01:153), as D-19 amends that column.
 */
export const PURPOSE_WORDS = {
  entry: { string: "Entry", source: "D02:264" },
  take_profit: { string: "Take profit", source: "D02:264" },
  stop_loss: { string: "Stop loss", source: "D02:264" },
  scale_in: { string: "Scale-in", source: "D01:153" },
  scale_out: { string: "Scale-out", source: "D01:153" },
  flatten: { string: "Flatten", source: "D01:153" },
  reverse: { string: "Reverse", source: "D01:153" },
  algo_child: { string: "Algo child", source: "D01:153" },
} as const satisfies Readonly<Record<string, CitedText>>;

/** D02 §6.1's separator between two words of one cell ("Limit · Take profit"). */
export const WORD_SEPARATOR = " · ";

/** A PROPOSED entry: the deck's shape, and the gap it fills (BQ-9). */
export interface ProposedEntry extends DeckEntry {
  readonly status: "PROPOSED";
  readonly gap: string;
}

const proposed = (
  string: string,
  gap: string,
  params?: Readonly<Record<string, string>>,
  announce: DeckEntry["announce"] = "none",
): ProposedEntry => ({
  string,
  screen: "SCR-063",
  owner: "E29-D03",
  status: "PROPOSED",
  announce,
  source: "#912 BQ-9",
  gap,
  ...(params === undefined ? {} : { params }),
});

/** BQ-9's words, PROPOSED to E29-D03's copy owner (G-W3); the strings are this story's. */
export const PROPOSED = {
  "blotter.ui.trigger.undirected": proposed(
    "Mark reaches 63,950.0",
    "A trigger whose direction is null and not derivable from a closing side (BQ-17).",
    { Mark: "trigger source", "63,950.0": "figure" },
  ),
  "blotter.ui.trigger.unsourced": proposed(
    "Price falls to 63,950.0",
    "A trigger with no `trigger_by`: D02:269 draws Mark and Last only.",
    { "falls to": "direction", "63,950.0": "figure" },
  ),
  "blotter.ui.trigger.bare": proposed(
    "Price reaches 63,950.0",
    "A trigger with neither a direction nor a `trigger_by`: D02:269 draws neither.",
    { "63,950.0": "figure" },
  ),
  "blotter.ui.parent.oco": proposed(
    "OCO",
    "The Parent column's word for an `oco` parent: D02:273 draws Bracket and TWAP, E30-D06 words Iceberg, Chase and Scaled, and no design words OCO.",
  ),
  "blotter.ui.orders_group": proposed(
    "Main · LIVE · 3 orders",
    'The account group row of the Working-orders tab: board 06 draws "Main · LIVE · 1 order"; §6 gives none.',
    { Main: "account label", LIVE: "environment", "3": "count" },
  ),
  "blotter.ui.orders_group.one": proposed(
    "Main · LIVE · 1 order",
    "The account group row with one order (board 06).",
    { Main: "account label", LIVE: "environment" },
  ),
  "blotter.ui.orders_group.no_env": proposed(
    "Main · 3 orders",
    "The account group row while its environment is not known: no empty segment.",
    { Main: "account label", "3": "count" },
  ),
  "blotter.ui.orders_group.no_env.one": proposed(
    "Main · 1 order",
    "The account group row with one order while its environment is not known.",
    { Main: "account label" },
  ),
  "blotter.ui.env.testnet": proposed(
    "TESTNET",
    "The testnet environment's word: D02 draws LIVE and DEMO only, and CMP-075's TESTNET look is PROPOSED too (`15`:848).",
  ),
  "blotter.ui.cancel.toast": proposed(
    "Cancel sent: BTCUSDT Sell 0.250 at 64,800.0 on Main.",
    "A single cancel's toast, without Undo, naming the order (D01 D7); the side's word, never its glyph.",
    {
      BTCUSDT: "symbol",
      Sell: "side",
      "0.250": "quantity",
      "64,800.0": "figure",
      Main: "account label",
    },
  ),
  "blotter.ui.bulk.count_orders": proposed(
    "2 orders on Sub-1 · LIVE",
    "The bulk cancel's count per account: the deck's `blotter.ui.bulk.count` counts positions.",
    { "2": "count", "Sub-1": "account label", LIVE: "environment" },
  ),
  "blotter.ui.bulk.cancel_title": proposed(
    "Cancel 4 orders?",
    "The bulk-cancel dialog's title (board 10: draft copy for E29-D03).",
    { "4": "count" },
  ),
  "blotter.ui.bulk.cancel_confirm": proposed(
    "Cancel 4 orders",
    "The bulk-cancel dialog's confirming button (board 10).",
    { "4": "count" },
  ),
  "blotter.ui.bulk.cancel_keep": proposed(
    "Keep orders",
    "The bulk-cancel dialog's dismissing button: never a second Cancel (board 10).",
  ),
  "blotter.ui.bulk.typed_word": proposed(
    "CANCEL",
    "LIVE's typed word for a bulk cancel (D02 §8.3: copy D03).",
  ),
  "blotter.ui.result.failed_partial": proposed(
    "Sub-4 · LIVE: cancelled 1, then Bybit stopped answering — the rest are still open",
    "An account that failed after cancelling some: the deck's line says nothing was cancelled.",
    { "Sub-4": "account label", LIVE: "environment", "1": "count" },
  ),
  "blotter.ui.result.failed_store": proposed(
    "Sub-2 · LIVE: nothing cancelled — CandleViewer could not read its orders",
    "`LegError.code` `store_unavailable`.",
    { "Sub-2": "account label", LIVE: "environment" },
  ),
  "blotter.ui.result.failed_other": proposed(
    "Sub-2 · LIVE: not all cancelled — try again",
    "Any other `LegError.code`; never its `message` or `exchange_ret_code`.",
    { "Sub-2": "account label", LIVE: "environment" },
  ),
  "blotter.quarantined": proposed(
    "Quarantined for review — nothing can be sent.",
    "A Quarantined order's Cancel reason (`22` refuses that cancel with 409).",
  ),
  "blotter.not_amendable": proposed(
    "This order can't be amended in its current state.",
    "Edit price, trigger or qty while Sending, Cancelling, Triggered or final (BQ-9: T2).",
  ),
  "blotter.ui.amend.not_sent": proposed(
    "Amend not sent — your order is unchanged",
    "An amend refused before any send (a 403, 409 or 422 answer).",
  ),
} as const satisfies Readonly<Record<string, ProposedEntry>>;

export type ProposedKey = keyof typeof PROPOSED;

/** A PROPOSED string with its spans bound, by `bindDeck`'s rule. */
export function bindProposed(
  key: ProposedKey,
  values: Readonly<Record<string, string>> = {},
): string {
  return bindEntry(key, PROPOSED[key], values);
}
