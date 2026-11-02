/**
 * The Positions tab's words (E29-S01 #911): the E29-D06 copy deck's keys, verbatim, with their
 * owners and sources (`docs/design/E29/E29-D06-copy.json`, v1 at base 927794a8ba). A test holds
 * every entry to the deck byte for byte, so a string changes only through its owner (D06 §6, BQ-17:
 * no string invented). The keys are this story's cut line (#911 BQ-2: S-01 to S-04, S-08, S-09's
 * tier part, S-14 to S-22, S-26) and BQ-14's account lines.
 *
 * Each data-bound span of a string is named in its `params` (D06 §6): `bindDeck` replaces those
 * spans with the caller's values, never the fixture's; a span marked `fixed` stays as written.
 * `D02_TEXT` holds the few strings merged E29-D02 draws and the deck does not key, each with its line.
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
} as const satisfies Readonly<Record<string, DeckEntry>>;

export type DeckKey = keyof typeof DECK;

/**
 * Merged E29-D02 strings the deck does not key (each cited; a test finds it at its line): the
 * kill-switch lock's header marker (D02:422) and the totals row's label (D02:142, :209).
 */
export const D02_TEXT = {
  killLockMarker: { string: "Locked — kill switch", source: "D02:422" },
  liveTotal: { string: "LIVE total", source: "D02:142" },
  demoTotal: { string: "DEMO total", source: "D02:209" },
} as const;

/** E09-D09 §3.2's verbs for the Viewer's two `rbac.permission` lines, in D02:433's order. */
export const RBAC_VERBS = {
  "positions:write": "change positions",
  "orders:write": "place orders",
} as const;

/**
 * The deck string of `key` with each bound span replaced: `values` maps a span as the deck writes
 * it ("Sub-1", "{account}") to the caller's text. Every span but a `fixed` one must be bound, so a
 * fixture label never reaches the screen.
 */
export function bindDeck(key: DeckKey, values: Readonly<Record<string, string>> = {}): string {
  const entry: DeckEntry = DECK[key];
  const spans = Object.entries(entry.params ?? {})
    .filter(([, kind]) => kind !== "fixed")
    .map(([span]) => span);
  const missing = spans.filter((span) => !Object.hasOwn(values, span));
  if (missing.length > 0) throw new TypeError(`${key}: unbound ${missing.join(", ")}`);
  // Spans are found in the deck's own string, left to right, so a bound value is never re-read.
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

/**
 * The panel-header notice of a read-only role (D02 §10.4, S-22): one `rbac.permission` line per
 * write the session lacks, verbatim. Presentation only: the server enforces (C-12.4).
 */
export function permissionLines(permissions: readonly string[]): readonly string[] {
  return (Object.keys(RBAC_VERBS) as (keyof typeof RBAC_VERBS)[])
    .filter((permission) => !permissions.includes(permission))
    .map((permission) => bindDeck("rbac.permission", { "{verb}": RBAC_VERBS[permission] }));
}
