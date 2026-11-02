/**
 * The Positions tab's words (E29-S01 #911): the E29-D06 copy deck's keys, verbatim, with their
 * owners and sources (`docs/design/E29/E29-D06-copy.json`, v1 at base 927794a8ba). A test holds
 * every entry to the deck byte for byte, so a string changes only through its owner (D06 §6, BQ-17:
 * no string invented). The keys are this story's cut line (#911 BQ-2: S-01 to S-04, S-08, S-09's
 * tier part, S-14 to S-22, S-26) and BQ-14's account lines; E29-S02 (#912) adds the Working-orders
 * tab's: S-12's amend moments, S-13, S-35 and S-36's orders half (its BQ-2, BQ-4, BQ-5).
 *
 * Each data-bound span of a string is named in its `params` (D06 §6): `bindDeck` replaces those
 * spans with the caller's values, never the fixture's; a span marked `fixed` stays as written.
 * `D02_TEXT` and `D03_TEXT` hold the few merged E29-D02 and E29-D03 strings the deck does not key,
 * each with its line.
 */

export interface DeckEntry {
  readonly string: string;
  readonly screen: string;
  readonly owner: string;
  readonly status: "merged" | "registered" | "PROPOSED";
  readonly announce: "none" | "polite" | "assertive";
  readonly source: string;
  readonly key_status?: string;
  readonly safety?: boolean;
  readonly params?: Readonly<Record<string, string>>;
}

export const DECK_VERSION = { pack: "E29-D06", version: "v1", base: "927794a8ba" } as const;

export const DECK = {
  "blotter.ui.loading": {
    string: "Loading Sub-1 · LIVE…",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:388",
    key_status: "PROPOSED name",
    params: { "Sub-1": "account label", LIVE: "environment" },
  },
  "blotter.ui.snapshot_failed": {
    string: "Could not load Sub-1 · LIVE",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "polite",
    source: "D02:389",
    key_status: "PROPOSED name",
    params: { "Sub-1": "account label", LIVE: "environment" },
  },
  "blotter.ui.empty": {
    string: "No open positions",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:390",
    key_status: "PROPOSED name",
  },
  "blotter.ui.empty_cause": {
    string: "Positions you open on any account appear here.",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:390",
    key_status: "PROPOSED name",
  },
  "blotter.ui.no_accounts": {
    string: "No accounts to show. None is assigned to you, or your access to them is frozen.",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:391",
    key_status: "PROPOSED name",
  },
  "blotter.ui.filter_empty": {
    string: "No rows match 2 filters",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:380",
    key_status: "PROPOSED name",
    params: { "2": "count" },
  },
  "panel.no_longer_shown": {
    string: "No longer shown — access to {account} was withdrawn.",
    screen: "SCR-063",
    owner: "E09-D09",
    status: "registered",
    announce: "polite",
    source: "D04:455",
    params: { "{account}": "placeholder" },
  },
  "inflight.pending": {
    string: "Outcome pending — see Orders",
    screen: "SCR-063",
    owner: "E09-D09",
    status: "registered",
    announce: "none",
    source: "D02:400",
  },
  "blotter.ui.liq.near": {
    string: "! Near 1.2",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "polite",
    source: "D02:219",
    key_status: "PROPOSED name",
    params: { "1.2": "figure" },
  },
  "blotter.ui.liq.critical": {
    string: "!! Critical 0.5",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "assertive",
    source: "D02:220",
    key_status: "PROPOSED name",
    params: { "0.5": "figure" },
  },
  "acct.reconciling.line": {
    string:
      "Sub-1 · LIVE — Reconciling with the exchange… Values shown are the last Bybit confirmed. Closing, cancelling and tightening stops still work.",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "merged",
    announce: "none",
    source: "D03:309",
    safety: true,
    params: { "Sub-1": "account label", LIVE: "environment" },
  },
  "acct.marker.checking": {
    string: "checking",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "merged",
    announce: "none",
    source: "D03:311",
  },
  "acct.announce.reconciling": {
    string: "Reconciling Sub-1 with Bybit. Closing, cancelling and tightening stops still work.",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "merged",
    announce: "polite",
    source: "D03:327",
    safety: true,
    params: { "Sub-1": "account label" },
  },
  "acct.announce.synced": {
    string: "Sub-1 reconciled with Bybit.",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "merged",
    announce: "polite",
    source: "D03:330",
    params: { "Sub-1": "account label" },
  },
  "acct.desync.line": {
    string:
      "Sub-1 · LIVE — Position data is being verified — actions temporarily limited. Bybit's values replace CandleViewer's as they are confirmed. Closing, cancelling and tightening stops still work.",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "merged",
    announce: "none",
    source: "D03:312",
    safety: true,
    params: { "Sub-1": "account label", LIVE: "environment" },
  },
  "acct.marker.verifying": {
    string: "Verifying",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "merged",
    announce: "none",
    source: "D03:313",
  },
  "acct.announce.desync": {
    string:
      "Sub-1: position data is being verified. New orders placed here are paused; closing, cancelling and tightening stops still work.",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "merged",
    announce: "polite",
    source: "D03:328",
    safety: true,
    params: { "Sub-1": "account label" },
  },
  "acct.stale.line": {
    string:
      "Sub-2 · LIVE is stale — CandleViewer could not reconcile it with Bybit for 2 minutes. New orders are locked until the owner resolves it; closing, cancelling and tightening stops still work.",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "merged",
    announce: "none",
    source: "D03:314",
    safety: true,
    params: { "Sub-2": "account label", LIVE: "environment", "2": "fixed" },
  },
  "acct.stale.line.nocause": {
    string:
      "Sub-2 · LIVE is stale — new orders are locked until the owner resolves it; closing, cancelling and tightening stops still work.",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "merged",
    announce: "none",
    source: "D03:316",
    safety: true,
    params: { "Sub-2": "account label", LIVE: "environment" },
  },
  "acct.marker.stale": {
    string: "Stale — locked since 14:04:11 UTC",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "merged",
    announce: "none",
    source: "D03:321",
    params: { "14:04:11": "time (UTC)" },
  },
  "acct.announce.stale": {
    string:
      "Sub-2 is locked for new orders: reconciliation with Bybit failed for 2 minutes. Closing, cancelling and tightening stops still work.",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "merged",
    announce: "assertive",
    source: "D03:329",
    safety: true,
    params: { "Sub-2": "account label", "2": "fixed" },
  },
  "acct.killlock.line": {
    string:
      "Sub-2 · LIVE is still locked for new orders after the kill switch; the owner must resolve it. Closing, cancelling and tightening stops still work, each sent at once.",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "merged",
    announce: "none",
    source: "D03:317",
    safety: true,
    params: { "Sub-2": "account label", LIVE: "environment" },
  },
  "blotter.ui.ks_owner": {
    string: "Kill switch active — engaged by the owner at 14:02:11 UTC",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:420",
    key_status: "PROPOSED name",
    params: { "14:02:11": "time (UTC)" },
  },
  "blotter.ui.ks_manager": {
    string: "Kill switch active since 14:02:11 UTC",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:421",
    key_status: "PROPOSED name",
    params: { "14:02:11": "time (UTC)" },
  },
  "blotter.ui.ks_ask": {
    string: "Ask the owner to close or release.",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:421",
    key_status: "PROPOSED name",
  },
  // S-21's chip: its consumer comes with B20's runtime machine (the orchestrator's carry on #911)
  "blotter.ui.lockout_chip": {
    string: "Locked · daily loss limit · until 00:00 UTC · closing and reducing still work",
    screen: "SCR-063",
    owner: "E39-D01",
    status: "registered",
    announce: "assertive",
    source: "D04:458",
    key_status: "PROPOSED name",
    safety: true,
    params: { "00:00": "time (UTC)" },
  },
  "rbac.permission": {
    string: "Your role can't {verb}.",
    screen: "SCR-063",
    owner: "E09-D09",
    status: "registered",
    announce: "none",
    source: "D04:450",
    params: { "{verb}": "placeholder" },
  },
  "rbac.account_read_only": {
    string: "You can view this account, not trade it.",
    screen: "SCR-063",
    owner: "E09-D09",
    status: "registered",
    announce: "none",
    source: "D04:453",
  },
  "rbac.view_as": {
    string: "Read-only while viewing as {user}.",
    screen: "SCR-063",
    owner: "E09-D09",
    status: "registered",
    announce: "none",
    source: "D04:449",
    params: { "{user}": "placeholder" },
  },
  "rbac.account": {
    string: "This account isn't assigned to you.",
    screen: "SCR-063",
    owner: "E09-D09",
    status: "registered",
    announce: "none",
    source: "D04:453",
  },
  "rbac.env": {
    string: "Live trading isn't enabled for you.",
    screen: "SCR-063",
    owner: "E09-D09",
    status: "registered",
    announce: "none",
    source: "D04:454",
  },
  "rbac.owner_only": {
    string: "Only the owner can {verb}.",
    screen: "SCR-063",
    owner: "E09-D09",
    status: "registered",
    announce: "none",
    source: "D04:451",
    params: { "{verb}": "placeholder" },
  },
  "glyph.name": {
    string: "Not available",
    screen: "SCR-063",
    owner: "E09-D09",
    status: "registered",
    announce: "none",
    source: "D04:455",
  },
  "inflight.not_sent": {
    string: "Not sent — your access changed. {reason}",
    screen: "SCR-063",
    owner: "E09-D09",
    status: "registered",
    announce: "none",
    source: "D04:455",
    params: { "{reason}": "placeholder" },
  },
  "arm.refused": {
    string: "One-click trading is locked",
    screen: "SCR-063",
    owner: "E30-D02",
    status: "registered",
    announce: "none",
    source: "D04:457",
  },
  "blotter.ui.tab.trade_groups": {
    string: "Trade groups are not available yet",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:166",
    key_status: "PROPOSED name",
  },
  "blotter.ui.tab.algos": {
    string: "Algos are not available yet",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:166",
    key_status: "PROPOSED name",
  },
  // E29-S02 (#912): S-12, the amend moments (BQ-2): `sl.*` waits for `setPositionTpSl` (E32, BQ-5).
  "blotter.ui.amend.editing": {
    string: "Editing — 2,500.00 is live",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:319",
    key_status: "PROPOSED name",
    params: { "2,500.00": "figure" },
  },
  "blotter.ui.amend.pending": {
    string: "Amending → 2,495.00 · 2,500.00 still live",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:320",
    key_status: "PROPOSED name",
    params: { "2,495.00": "figure", "2,500.00": "figure" },
  },
  "blotter.ui.amend.unconfirmed": {
    string: "Unknown — checking · 2,500.00 may still be live",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:321",
    key_status: "PROPOSED name",
    params: { "2,500.00": "figure" },
  },
  "blotter.ui.amend.confirmed": {
    string: "Amend confirmed: price 2,495.00.",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "polite",
    source: "D02:322",
    key_status: "PROPOSED name",
    params: { "2,495.00": "figure" },
  },
  "blotter.ui.amend.rejected": {
    string: "Amend rejected — your order is unchanged",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:323",
    key_status: "PROPOSED name",
  },
  "blotter.ui.amend.rejected_desc": {
    string: "Amend rejected. Your order is unchanged: the price is still 2,500.00.",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "assertive",
    source: "D02:323",
    key_status: "PROPOSED name",
    params: { "2,500.00": "figure" },
  },
  "blotter.amend_in_flight": {
    string: "An amend is already in flight.",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "PROPOSED",
    announce: "none",
    source: "D04:464",
  },
  // E29-S02 (#912): S-13, the rows no one may send for, and the native stop's Cancel (BQ-5).
  "blotter.untracked": {
    string: "Not placed by CandleViewer — manage it on Bybit.",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "PROPOSED",
    announce: "none",
    source: "D04:465",
  },
  "blotter.held": {
    string: "Held for owner review — nothing can be sent.",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "PROPOSED",
    announce: "none",
    source: "D04:465",
  },
  "blotter.unknown": {
    string: "We could not confirm this order with Bybit; checking.",
    screen: "SCR-063",
    owner: "E29-D03",
    status: "PROPOSED",
    announce: "none",
    source: "D04:465",
  },
  "sl.note": {
    string: "Every position keeps a native stop — you can move it, not delete it.",
    screen: "SCR-063",
    owner: "E32-D01",
    status: "PROPOSED",
    announce: "none",
    source: "D04:466",
    safety: true,
  },
  // E29-S02 (#912): offline with REST unreachable, every cancel T2 behind this notice (D02:397).
  "blotter.ui.unreachable": {
    string: "Cannot reach server",
    screen: "SCR-063",
    owner: "E17-D01",
    status: "registered",
    announce: "none",
    source: "D04:459",
    key_status: "PROPOSED name",
  },
  "blotter.ui.cancel.split": {
    string: "Cancel ▾",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:153",
    key_status: "PROPOSED name",
  },
  // E29-S02 (#912): S-35, the two sections.
  "blotter.ui.section.working": {
    string: "Working · 3",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:281",
    key_status: "PROPOSED name",
    params: { "3": "count" },
  },
  "blotter.ui.section.conditional": {
    string: "Conditional — not triggered · 2",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:281",
    key_status: "PROPOSED name",
    params: { "2": "count" },
  },
  // E29-S02 (#912): S-36's Working-orders half (BQ-4): Cancel selected, Cancel all in view,
  // the result, Retry failed.
  "blotter.ui.sel.bar": {
    string: "2 selected · Close selected · Clear selection",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "polite",
    source: "D02:349",
    key_status: "PROPOSED name",
    params: { "2": "count" },
  },
  "blotter.ui.sel.cancel": {
    string: "Cancel selected",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:349",
    key_status: "PROPOSED name",
  },
  "blotter.ui.bulk.cancel_all": {
    string: "Cancel all in view…",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:349",
    key_status: "PROPOSED name",
  },
  "blotter.ui.bulk.excluded": {
    string: "1 native-stop order is not included: every position keeps a native stop.",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:349",
    key_status: "PROPOSED name",
    params: { "1": "count" },
    safety: true,
  },
  "blotter.ui.bulk.tp_excluded": {
    string: "1 take-profit is not included: an amend is already in flight.",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:349",
    key_status: "PROPOSED name",
    params: { "1": "count" },
  },
  "blotter.ui.result.done": {
    string: "Cancelled 4 on Main · LIVE",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:349",
    key_status: "PROPOSED name",
    params: { "4": "count", Main: "account label", LIVE: "environment" },
  },
  "blotter.ui.result.failed": {
    string: "Sub-1 · LIVE: Bybit did not answer — nothing cancelled",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:349",
    key_status: "PROPOSED name",
    params: { "Sub-1": "account label", LIVE: "environment" },
  },
  "blotter.ui.result.retry": {
    string: "Retry failed",
    screen: "SCR-063",
    owner: "E29-D02",
    status: "merged",
    announce: "none",
    source: "D02:349",
    key_status: "PROPOSED name",
  },
} as const satisfies Readonly<Record<string, DeckEntry>>;

export type DeckKey = keyof typeof DECK;

/**
 * Merged E29-D02 strings the deck does not key (each cited; a test finds it at its line): the
 * kill-switch lock's header marker (D02:422), the totals row's label (D02:142, :209), and the
 * panel's own words: the five tabs and two placeholders' causes (D02:166), the toolbar (D02:374 to
 * :376), filter-empty's button (D02:380) and S-02's Retry (D02:389).
 */
export const D02_TEXT = {
  killLockMarker: { string: "Locked — kill switch", source: "D02:422" },
  liveTotal: { string: "LIVE total", source: "D02:142" },
  demoTotal: { string: "DEMO total", source: "D02:209" },
  tabPositions: { string: "Positions", source: "D02:166" },
  tabWorkingOrders: { string: "Working orders", source: "D02:166" },
  tabFills: { string: "Fills", source: "D02:166" },
  tabTradeGroups: { string: "Trade groups", source: "D02:166" },
  tabAlgos: { string: "Algos", source: "D02:166" },
  tradeGroupsCause: {
    string: "Grouped orders across accounts will be listed here.",
    source: "D02:166",
  },
  algosCause: { string: "Running algorithms will be listed here.", source: "D02:166" },
  groupBy: { string: "Group by", source: "D02:374" },
  groupAccount: { string: "Account", source: "D02:374" },
  groupSymbol: { string: "Symbol", source: "D02:374" },
  groupTradeGroup: { string: "Trade group", source: "D02:374" },
  addFilter: { string: "Filter", source: "D02:375" },
  chipAccount: { string: "Account", source: "D02:375" },
  chipSymbol: { string: "Symbol", source: "D02:375" },
  chipSide: { string: "Side", source: "D02:375" },
  columns: { string: "Columns", source: "D02:376" },
  exportCsv: { string: "Export CSV", source: "D02:376" },
  clearFilters: { string: "Clear filters", source: "D02:380" },
  retry: { string: "Retry", source: "D02:389" },
  envLive: { string: "LIVE", source: "D02:238" },
  envDemo: { string: "DEMO", source: "D02:209" },
} as const;

/** A string and its data-bound spans: a deck entry, or a merged string the deck does not key. */
export interface BoundText {
  readonly string: string;
  readonly params?: Readonly<Record<string, string>>;
}

/**
 * Merged E29-D03 strings the deck does not key (each cited; a test finds it at its line): D03 §5.2
 * words `acct.announce.stale` by §4.1's variant (D03:329), and the deck keys only the failure one.
 * No client reads B19, so no lock's cause is known: every role hears the cause-not-shown sentence,
 * and a stale notice under a covering kill switch the kill-switch sentence (D03 §4.1, RT-07). Both
 * are assertive, once per episode (D03 §8.3). The deck's gap is routed to E29-D06's owner. D03:329's
 * conditional ending ("2 open positions have no confirmed exchange-side stop.") is left off: the WS
 * `positions` row carries no `native_stop_present` (`23`:917), so no client can count them.
 */
export const D03_TEXT = {
  staleAnnounce: {
    string:
      "Sub-2 is locked for new orders until the owner resolves it. Closing, cancelling and tightening stops still work.",
    source: "D03:329",
    params: { "Sub-2": "account label" },
  },
  killLockAnnounce: {
    string:
      "Sub-2 is still locked for new orders after the kill switch. Closing, cancelling and tightening stops still work.",
    source: "D03:329",
    params: { "Sub-2": "account label" },
  },
} as const satisfies Readonly<Record<string, BoundText & { readonly source: string }>>;

/**
 * PROPOSED words (#911 BQ-15, routed to E29-D03's copy owner through G-W3 and listed in the PR body
 * for the ledger row): the Fills placeholder, which no deck or D02 line draws (E29-S02 replaced the
 * Working orders one with its tab), the words the panel composes where no design gives a string (a trade group's name and the
 * positions with none, the crossing and value announcements, the export's file name), and the
 * environment words for a session D02 does not draw (TESTNET, the shell badge's PROPOSED word).
 * `filterEmptyOne` is filter-empty's singular, proposed as `blotter.ui.filter_empty#2`: the deck's
 * one form reads "No rows match 1 filters" for the commonest case, one Account chip.
 */
export const PROPOSED_TEXT = {
  fillsTitle: "Fills are not available yet",
  fillsCause: "Fills across accounts will be listed here.",
  tradeGroupLabel: "Trade group …{stub}",
  noTradeGroup: "No trade group",
  envTestnet: "TESTNET",
  testnetTotal: "TESTNET total",
  exportFileName: "candleviewer-positions-{stamp}.csv",
  filterEmptyOne: "No rows match 1 filter",
} as const;

/** The values a deck string's data-bound spans take, by the kind its `params` name (D06 §6). */
export interface DeckValues {
  readonly label?: string;
  readonly environment?: string;
  readonly time?: string;
  readonly count?: string;
  readonly figure?: string;
}

const SPAN_KINDS: Readonly<Record<string, keyof DeckValues>> = {
  "account label": "label",
  environment: "environment",
  "time (UTC)": "time",
  count: "count",
  figure: "figure",
};

/**
 * `text` with each span bound by its kind ("account label", "environment", ...), so one call fits
 * every string of a family whatever fixture word it wrote ("Sub-1", "Sub-2"). A span left unbound
 * throws, as `bindText` does; `name` says whose in the error.
 */
export function bindTextKinds(text: BoundText, name: string, values: DeckValues): string {
  const spans: Record<string, string> = {};
  for (const [span, kind] of Object.entries(text.params ?? {})) {
    const field = Object.hasOwn(SPAN_KINDS, kind) ? SPAN_KINDS[kind] : undefined;
    const value = field === undefined ? undefined : values[field];
    if (value !== undefined) spans[span] = value;
  }
  return bindText(text, name, spans);
}

/** The deck string of `key`, its spans bound by kind (`bindTextKinds`). */
export const bindKinds = (key: DeckKey, values: DeckValues): string =>
  bindTextKinds(DECK[key], key, values);

/** E09-D09 §3.2's verbs for the Viewer's two `rbac.permission` lines, in D02:433's order. */
export const RBAC_VERBS = {
  "positions:write": "change positions",
  "orders:write": "place orders",
} as const;

/**
 * `text` with each bound span replaced: `values` maps a span as the string writes it ("Sub-1",
 * "{account}") to the caller's text. Every span but a `fixed` one must be bound, so a fixture label
 * never reaches the screen; `name` says whose in the error.
 */
export function bindText(
  text: BoundText,
  name: string,
  values: Readonly<Record<string, string>> = {},
): string {
  const spans = Object.entries(text.params ?? {})
    .filter(([, kind]) => kind !== "fixed")
    .map(([span]) => span);
  const missing = spans.filter((span) => !Object.hasOwn(values, span));
  if (missing.length > 0) throw new TypeError(`${name}: unbound ${missing.join(", ")}`);
  // Spans are found in the string itself, left to right, so a bound value is never re-read.
  const found = spans
    .map((span) => ({ span, at: text.string.indexOf(span) }))
    .filter(({ at }) => at >= 0)
    .sort((a, b) => a.at - b.at);
  let out = "";
  let from = 0;
  for (const { span, at } of found) {
    if (at < from) continue; // overlapping spans: the first wins
    out += text.string.slice(from, at) + (values[span] ?? span);
    from = at + span.length;
  }
  return out + text.string.slice(from);
}

/** The deck string of `key`, each bound span replaced (`bindText`). */
export const bindDeck = (key: DeckKey, values: Readonly<Record<string, string>> = {}): string =>
  bindText(DECK[key], key, values);

/**
 * `bindDeck`'s rule for any entry of the deck's shape: a PROPOSED string the deck does not key yet
 * (E29-S02's `orders/copy.ts`) binds the same way, by the spans its `params` name.
 */
export const bindEntry = (
  key: string,
  entry: DeckEntry,
  values: Readonly<Record<string, string>> = {},
): string => bindText(entry, key, values);

export type WritePermission = keyof typeof RBAC_VERBS;

/**
 * The panel-header notice of a read-only role (D02 §10.4, S-22): one `rbac.permission` line per
 * write the session lacks, verbatim, with the permission it names. Presentation only: the server
 * enforces (C-12.4).
 */
export function permissionLines(
  permissions: readonly string[],
): readonly { readonly permission: WritePermission; readonly line: string }[] {
  return (Object.keys(RBAC_VERBS) as WritePermission[])
    .filter((permission) => !permissions.includes(permission))
    .map((permission) => ({
      permission,
      line: bindDeck("rbac.permission", { "{verb}": RBAC_VERBS[permission] }),
    }));
}
