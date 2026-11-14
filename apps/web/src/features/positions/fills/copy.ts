/**
 * The fills' words (E29-S04 #979), the positions copy's pattern (`../copy.ts`): every string is the
 * E29-D06 deck's, byte for byte, or a merged design string held to its line, so a string changes
 * only through its owner (D06 §6: no string invented).
 *
 * - **`DECK`**: the deck's 41 `fills.*` keys (`E29-D06-copy.json`, v1 at base 927794a8ba), from
 *   D03 §5.1 (D03:261–301). A test holds each entry to the deck.
 * - **`D03_TEXT`**: the other strings of D03 §5.1's multi-string rows, which the deck keeps only
 *   the first of (BQ-5), lifted verbatim, each held by a test to its line. The deck delta is routed
 *   to D06's owner.
 * - **`D02_TEXT`**: the Fills tab's words D02:299 draws and the deck does not key (BQ-13).
 * - **`STATE_WORDS`**: E29-D01 D2's state words (D01:177–191) for `fills.empty.order`, whose deck
 *   string fixes "Working" (BQ-5). `orders/copy.ts` (#912) holds the same table; it is not on
 *   `main`, so this cited copy stands in until it is (a deviation, recorded on #979).
 * - **`PROPOSED_TEXT`**: words no merged design draws, routed to G-W3, each held out of the deck.
 */
import type { DeckEntry } from "../copy";

/** A merged design string and the line it is drawn at; `params` names its bound spans. */
export interface CitedText {
  readonly string: string;
  readonly source: string;
  readonly params?: Readonly<Record<string, string>>;
}

export const DECK_VERSION = { pack: "E29-D06", version: "v1", base: "927794a8ba" } as const;

/** A D03 §5.1 deck entry: SCR-078's, owned by E29-D03, merged. */
function d03(
  string: string,
  line: number,
  announce: DeckEntry["announce"] = "none",
  params?: Readonly<Record<string, string>>,
): DeckEntry {
  const entry = { string, screen: "SCR-078", owner: "E29-D03", status: "merged" } as const;
  return { ...entry, announce, source: `D03:${line}`, ...(params !== undefined && { params }) };
}

export const DECK = {
  "fills.title.order": d03("Fills — order …a3f2 · BTCUSDT ▲ Buy · Main · LIVE", 261, "none", {
    "…a3f2": "short id",
    BTCUSDT: "symbol",
    "▲ Buy": "side",
    Main: "account label",
    LIVE: "environment",
  }),
  "fills.title.group": d03(
    "Fills — trade group …7c1e · BTCUSDT ▲ Buy · 3 accounts · LIVE",
    262,
    "none",
    { "…7c1e": "short id", BTCUSDT: "symbol", "▲ Buy": "side", "3": "count", LIVE: "environment" },
  ),
  "fills.title.position": d03(
    "Fills — closed BTCUSDT long · Sub-1 · LIVE · 13:58–14:03 UTC",
    263,
    "none",
    {
      BTCUSDT: "symbol",
      long: "side",
      "Sub-1": "account label",
      LIVE: "environment",
      "13:58–14:03": "time window (UTC)",
    },
  ),
  "fills.chrome": d03("Time", 264),
  "fills.scope": d03("Limit 63,420.0 · Filled · placed 14:02:10 UTC", 265, "none", {
    "63,420.0": "figure",
    "14:02:10": "time (UTC)",
  }),
  "fills.section": d03(
    "Main · LIVE — 0.300 BTC · avg 63,496.67 · 33 % maker · −8.25 USDT · 1.00 USDT better",
    266,
    "none",
    {
      Main: "account label",
      LIVE: "environment",
      "0.300 BTC": "quantity",
      "63,496.67": "figure",
      "33 %": "percentage",
      "−8.25 USDT": "money (USDT)",
      "1.00 USDT": "money (USDT)",
    },
  ),
  "fills.footer": d03("3 fills · newest first · times UTC", 267, "none", { "3": "count" }),
  "fills.sum.filled": d03("Filled 0.250 of 0.250 BTC · 3 fills", 268, "none", {
    "0.250": "figure",
    "0.250 BTC": "quantity",
    "3": "count",
  }),
  "fills.sum.avg": d03("Avg price 63,414.02", 269, "none", { "63,414.02": "figure" }),
  "fills.sum.split": d03("Liquidity 24 % maker · 76 % taker by quantity", 270, "none", {
    "24 %": "percentage",
    "76 %": "percentage",
  }),
  "fills.sum.fees": d03("Fees −7.39 USDT paid", 271, "none", { "−7.39 USDT": "money (USDT)" }),
  "fills.sum.slip.better": d03(
    "Slippage −5.98 (59.8 ticks) · 1.50 USDT better than the limit 63,420.0",
    272,
    "none",
    { "−5.98": "figure", "59.8 ticks": "ticks", "1.50 USDT": "money (USDT)", "63,420.0": "figure" },
  ),
  "fills.sum.slip.worse": d03(
    "Slippage +20.00 (200 ticks) · 5.00 USDT worse than the trigger 63,900.0",
    273,
    "none",
    { "+20.00": "figure", "200 ticks": "ticks", "5.00 USDT": "money (USDT)", "63,900.0": "figure" },
  ),
  "fills.sum.slip.none": d03("Slippage — · a market order has no intended price", 274),
  "fills.sum.slip.amended": d03(
    "Slippage −0.40 (4 ticks) · 0.04 USDT better than the amended limit 63,400.0",
    275,
    "none",
    { "−0.40": "figure", "4 ticks": "ticks", "0.04 USDT": "money (USDT)", "63,400.0": "figure" },
  ),
  "fills.sum.partial": d03("So far: 500 fills — loading more", 276, "none", { "500": "count" }),
  "fills.link.*": d03("Trade group …7c1e", 277, "none", { "…7c1e": "short id" }),
  "fills.link.diag": d03("Order diagnostics", 278),
  "fills.row.menu": d03("Copy exec id", 279),
  "fills.row.detail": d03("Exec id {full}", 280, "none", { "{full}": "placeholder" }),
  "fills.type.*": d03("Trade", 281),
  "fills.cell.null": d03("—", 282),
  "fills.pill.new": d03("3 new fills", 283, "none", { "3": "count" }),
  "fills.provisional": d03("Provisional — fees pending", 284),
  "fills.pos.check": d03(
    "These fills do not add up to the closed 0.250 BTC — totals are not final.",
    285,
    "none",
    { "0.250 BTC": "quantity" },
  ),
  "fills.pos.hedge": d03(
    "Hedge mode: fills of both sides in this window are listed — totals are not final.",
    286,
  ),
  "fills.announce.adl": d03("ADL reduced BTCUSDT on Main · LIVE.", 287, "assertive", {
    BTCUSDT: "symbol",
    Main: "account label",
    LIVE: "environment",
  }),
  "fills.empty.order": d03("No fills for this order yet — it is Working.", 288),
  "fills.empty.group": d03("No fills for this trade group yet.", 289),
  "fills.empty.window": d03("No fills on Sub-1 between 13:58 and 14:03 UTC.", 290, "none", {
    "Sub-1": "account label",
    "13:58": "time (UTC)",
    "14:03": "time (UTC)",
  }),
  "fills.error": d03("Could not load fills. Try again.", 291, "polite"),
  "fills.revoked": d03("No longer shown — access to Sub-1 was withdrawn.", 292, "polite", {
    "Sub-1": "account label",
  }),
  "fills.offline": d03(
    "As of 14:02:11 UTC — new fills appear when the connection is back.",
    293,
    "none",
    { "14:02:11": "time (UTC)" },
  ),
  "fills.acct.checking": d03(
    "Sub-1 · LIVE is being checked against Bybit — fills it finds are added here.",
    294,
    "none",
    { "Sub-1": "account label", LIVE: "environment" },
  ),
  "fills.acct.stale": d03(
    "Sub-1 · LIVE is stale — fills may be missing until it is reconciled.",
    295,
    "none",
    { "Sub-1": "account label", LIVE: "environment" },
  ),
  "fills.acct.killlock": d03(
    "Sub-1 · LIVE is locked for new orders after the kill switch.",
    296,
    "none",
    { "Sub-1": "account label", LIVE: "environment" },
  ),
  "fills.export.button": d03("Export CSV", 297),
  "fills.export.progress": d03("Exporting… 500 fills so far", 298, "none", { "500": "count" }),
  "fills.export.done": d03("Exported 1,240 fills.", 299, "polite", { "1,240": "count" }),
  "fills.export.failed": d03(
    "Export failed — not every fill could be read. Try again.",
    300,
    "polite",
  ),
  "fills.export.watermark": d03(
    "# CandleViewer fills export — not the audit trail · exported by {display name} (Owner) · accounts: Main (LIVE) · generated 2026-10-22 14:05:09 UTC",
    301,
    "none",
    {
      "{display name}": "placeholder",
      Main: "account label",
      LIVE: "environment",
      "2026-10-22 14:05:09": "date-time (UTC)",
    },
  ),
} satisfies Readonly<Record<string, DeckEntry>>;

export type FillsKey = keyof typeof DECK;

/** D03 §5.1's other strings (BQ-5), by the deck key whose row draws them. */
export const D03_TEXT = {
  // fills.title.group: the Manager's form ends "… · your legs (2) · LIVE"
  yourLegs: { string: "your legs (2)", source: "D03:262", params: { "2": "count" } },
  // fills.chrome: the column headers and the summary's labels
  headerSide: { string: "Side", source: "D03:264" },
  headerType: { string: "Type", source: "D03:264" },
  headerPrice: { string: "Price", source: "D03:264" },
  headerQty: { string: "Qty (BTC)", source: "D03:264", params: { BTC: "base coin" } },
  headerFee: { string: "Fee", source: "D03:264" },
  headerLiquidity: { string: "Liquidity", source: "D03:264" },
  headerExecId: { string: "Exec id", source: "D03:264" },
  headerOrder: { string: "Order", source: "D03:264" },
  labelFilled: { string: "Filled", source: "D03:264" },
  labelAvg: { string: "Avg price", source: "D03:264" },
  labelFees: { string: "Fees", source: "D03:264" },
  labelSlippage: { string: "Slippage", source: "D03:264" },
  labelLinks: { string: "Links", source: "D03:264" },
  close: { string: "Close fills detail", source: "D03:264" },
  // fills.scope
  scopeGroup: {
    string: "Limit 63,500.0 · 3 legs · placed 14:05:02 UTC",
    source: "D03:265",
    params: { "63,500.0": "figure", "3": "count", "14:05:02": "time (UTC)" },
  },
  scopeManager: {
    string: "Limit 63,500.0 · your legs (2) · placed 14:05:02 UTC",
    source: "D03:265",
    params: { "63,500.0": "figure", "2": "count", "14:05:02": "time (UTC)" },
  },
  scopeWhole: { string: "Show the whole trade group", source: "D03:265" },
  // fills.section: the slippage at zero, and an order's section (D01 D14)
  sectionAtLimit: { string: "· at the limit", source: "D03:266" },
  sectionOrder: {
    string:
      "Exit · stop loss …91c4 — 0.250 BTC · avg 63,880.00 · 0 % maker · −8.78 USDT · 5.00 USDT worse",
    source: "D03:266",
  },
  // fills.sum.filled and fills.sum.avg: the scopes the order's own figures do not cover (D-6)
  filledGroup: { string: "Filled 0.600 BTC · 4 fills", source: "D03:268" },
  avgGroup: { string: "Avg price 63,497.83 · from 4 fills", source: "D03:269" },
  // fills.sum.fees
  feesReceived: { string: "Fees +0.84 USDT received", source: "D03:271" },
  feesProvisional: { string: "Fees −8.78 USDT paid · provisional", source: "D03:271" },
  feePending: { string: "1 fee pending", source: "D03:271", params: { "1": "count" } },
  // fills.sum.slip.amended: its description and tooltip
  amendedNote: { string: "The first intended price is not recorded.", source: "D03:275" },
  // fills.link.*
  linkNoGroup: { string: "No trade group", source: "D03:277" },
  linkRule: { string: "Rule BTC breakout long", source: "D03:277" },
  linkRuleStub: { string: "Rule …0003", source: "D03:277", params: { "…0003": "short id" } },
  linkNoRule: { string: "No rule recorded", source: "D03:277" },
  linkJournal: { string: "Journal trade", source: "D03:277" },
  linkJournalLater: { string: "Journal: when the trade closes", source: "D03:277" },
  linkNoJournal: { string: "No journal entry for this type", source: "D03:277" },
  diagMarker: { string: "Opening diagnostics is recorded in the audit log", source: "D03:278" },
  // fills.row.menu (a fill with no order leaves out the four order items)
  menuCopyOrder: { string: "Copy order id", source: "D03:279" },
  menuOpenOrder: { string: "Open order", source: "D03:279" },
  menuDiagnostics: { string: "Order diagnostics", source: "D03:279" },
  menuOpenGroup: { string: "Open trade group", source: "D03:279" },
  menuOpenRule: { string: "Open rule", source: "D03:279" },
  menuOpenJournal: { string: "Open journal trade", source: "D03:279" },
  // fills.type.*: the words beyond "Trade"; ADL's full name is its accessible name and tooltip
  typeAdl: { string: "ADL", source: "D03:281" },
  typeAdlName: { string: "ADL — auto-deleveraged", source: "D03:281" },
  typeLiquidation: { string: "Liquidation", source: "D03:281" },
  typeFunding: { string: "Funding", source: "D03:281" },
  typeSettlement: { string: "Settlement", source: "D03:281" },
  // fills.cell.null: each "—" is named by its reason (D-9)
  nullFee: { string: "fee not reported yet", source: "D03:282" },
  nullFeeCoin: { string: "fee currency not reported", source: "D03:282" },
  nullLiquidity: { string: "liquidity not reported", source: "D03:282" },
  nullType: { string: "type not reported", source: "D03:282" },
  nullOrder: { string: "no order for this type", source: "D03:282" },
  nullFeeDetail: {
    string: "Fee 3.49, currency not reported",
    source: "D03:282",
    params: { "3.49": "figure" },
  },
  // fills.row.detail: the detail line's figures
  detailValue: {
    string: "Value 6,341.00 USDT",
    source: "D03:280",
    params: { "6,341.00": "money" },
  },
  detailFeeRate: { string: "Fee rate 0.0550 %", source: "D03:280", params: { "0.0550": "figure" } },
  detailClosedPnl: {
    string: "Closed PnL −54.75 USDT",
    source: "D03:280",
    params: { "−54.75": "money" },
  },
  // D03 §3.3's other words: the sides and the liquidity flags, and the Order cell's name
  sideBuy: { string: "▲ Buy", source: "D03:140" },
  sideSell: { string: "▼ Sell", source: "D03:140" },
  maker: { string: "Maker", source: "D03:145" },
  taker: { string: "Taker", source: "D03:145" },
  orderEnding: { string: "order ending a3f2", source: "D03:147", params: { a3f2: "short id" } },
  // fills.announce.adl, fills.error, fills.revoked
  announceLiquidation: {
    string: "Liquidation reduced BTCUSDT on Main · LIVE.",
    source: "D03:287",
    params: { BTCUSDT: "symbol", Main: "account label", LIVE: "environment" },
  },
  retry: { string: "Retry", source: "D03:291" },
  revokedOther: { string: "No longer shown — access changed", source: "D03:292" },
  // fills.export.watermark's other identities, and D03 §3.8's file name
  exportedByManager: { string: "exported by alex (Manager)", source: "D03:301" },
  viewingAs: { string: ", viewing as alex", source: "D03:301", params: { alex: "user name" } },
  fileName: {
    string: "candleviewer-fills-order-a3f2-20261022T140509Z.csv",
    source: "D03:200",
    params: { a3f2: "short id", "20261022T140509Z": "date-time (UTC)" },
  },
} as const satisfies Readonly<Record<string, CitedText>>;

/** D02:299's Fills-tab words the deck does not key (BQ-13: the empty line cited, not keyed). */
export const D02_TEXT = {
  noRecentFills: {
    string: "No recent fills on Sub-1 · LIVE",
    source: "D02:299",
    params: { "Sub-1": "account label", LIVE: "environment" },
  },
  everyFill: { string: "Show every fill", source: "D02:299" },
} as const satisfies Readonly<Record<string, CitedText>>;

/** E29-D01 D2: the B1 `lifecycle` state's word (#912's `STATE_WORDS`, cited here). */
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

/**
 * Words no merged design draws (G-W3, PROPOSED): the Type chips restated in the filter-empty
 * state (BQ-13; D02:380 restates the panel's chips as "Account: Sub-1 · Symbol: SOLUSDT"), and
 * with none pressed; the Fills tab's export file name (D03:200's, without a scope); and a
 * Viewer's role in the watermark.
 */
export const PROPOSED_TEXT = {
  typeFilter: { string: "Type: Trade, ADL", params: { "Trade, ADL": "type words" } },
  typeFilterNone: { string: "Type: none" },
  tabFileName: {
    string: "candleviewer-fills-20261022T140509Z.csv",
    params: { "20261022T140509Z": "date-time (UTC)" },
  },
  exportedByViewer: { string: "exported by alex (Viewer)" },
} as const;

/**
 * `entry`'s string with each bound span replaced, `../copy.ts`'s `bindDeck` rule: `values` maps a
 * span as the string writes it ("Main", "{display name}") to the caller's text; every span but a
 * `fixed` one must be bound, so a fixture value never reaches the screen.
 */
export function bindEntry(
  entry: { readonly string: string; readonly params?: Readonly<Record<string, string>> },
  values: Readonly<Record<string, string>> = {},
): string {
  const spans = Object.entries(entry.params ?? {})
    .filter(([, kind]) => kind !== "fixed")
    .map(([span]) => span);
  const missing = spans.filter((span) => !Object.hasOwn(values, span));
  if (missing.length > 0) throw new TypeError(`unbound ${missing.join(", ")}`);
  // spans are found in the string as written, left to right, so a bound value is never re-read
  const found = spans
    .map((span) => ({ span, at: entry.string.indexOf(span) }))
    .filter(({ at }) => at >= 0)
    .sort((a, b) => a.at - b.at);
  let out = "";
  let from = 0;
  for (const { span, at } of found) {
    if (at < from) continue; // overlapping spans: the first wins
    out += entry.string.slice(from, at) + (values[span] ?? span);
    from = at + span.length;
  }
  return out + entry.string.slice(from);
}

export const bindFills = (key: FillsKey, values?: Readonly<Record<string, string>>): string =>
  bindEntry(DECK[key], values);

/** `fills.empty.order` with the order's state word in place of the deck's fixed "Working" (BQ-5). */
export const emptyOrderText = (state: keyof typeof STATE_WORDS): string =>
  bindEntry(
    { string: DECK["fills.empty.order"].string, params: { Working: "state word" } },
    {
      Working: STATE_WORDS[state].string,
    },
  );
