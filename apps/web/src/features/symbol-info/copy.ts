/**
 * The words of SCR-103 that the data layer composes: E08-D13's deck (`E08-D13-copy.json`, keys `d06.*`) and the
 * D06 sections it cites, verbatim. A string neither has is marked PROPOSED and carried as a G-row in the PR.
 */

export const DASH = "—";
/** D06 §4.1: a field the contract does not serve yet, in `color.text.tertiary`; never a number. */
export const NOT_AVAILABLE_YET = "not available yet";

/** D06 §1 / §3: the contract band's lead sentence (D-1). */
export const ENFORCED_NOTE =
  "These rules are enforced by the exchange. CandleViewer shows them and cannot change them.";

/** D06 §3, §4.1: the rows' labels. */
export const LABELS = {
  status: "Status",
  tick_size: "Tick size",
  qty_step: "Quantity step",
  min_order_qty: "Minimum quantity",
  max_order_qty: "Maximum quantity, limit orders",
  max_mkt_order_qty: "Maximum quantity, market orders",
  min_notional_value: "Minimum order value",
  max_leverage: "Maximum leverage",
  funding_interval: "Funding interval",
  risk_limit_tiers: "Risk-limit tiers",
} as const;

/** D06 §4.1: the Status row's words (§3 "Trading", "Pre-launch", "Delivering", "Closed"). */
export const STATUS_WORDS = {
  Trading: "Trading",
  PreLaunch: "Pre-launch",
  Delivering: "Delivering",
  Closed: "Closed",
} as const;

/** D06 §5's sentences, the stems of `policy.py` (`:168`, `:177`, `:193`, `:200`, `:209`) and §4.1's leverage line. */
export const SENTENCES = {
  tick: (tick: string): string => `Price must be a multiple of ${tick}.`,
  step: (step: string): string => `Quantity must be a multiple of ${step}.`,
  minQty: (min: string): string => `Quantity must be at least ${min}.`,
  maxQty: (max: string): string => `Quantity must not exceed ${max}.`,
  minValue: (min: string): string => `Order notional must be at least ${min}.`,
  leverageStep: (step: string): string => `Leverage is set in steps of ${step}.`,
} as const;

/** D06 §3's board: "50,000.04 → 50,000.0 (nearest)", "0.0019 → 0.001 (always down)". */
export const EXAMPLES = {
  nearest: (from: string, to: string): string => `${from} → ${to} (nearest)`,
  down: (from: string, to: string): string => `${from} → ${to} (always down)`,
  refused: (price: string, qty: string, value: string): string =>
    `${price} × ${qty} = ${value} → refused`,
} as const;

/** D06 §4.1: "8 h" for whole hours, else "30 min"; the tag beside it. */
export const FUNDING_CAN_CHANGE = "can change";
export const fundingInterval = (minutes: number): string =>
  minutes % 60 === 0 ? `${String(minutes / 60)} h` : `${String(minutes)} min`;

/** D06 §3 identity line, D-2 provenance, D-3 overdue notice. */
export const IDENTITY_SEPARATOR = " · ";
export const revisionText = (revision: number): string => `Rules revision ${String(revision)}`;
export const CHECKED_UNKNOWN = "checked —";
/** PROPOSED units for the age (D06 shows only "2 h ago" and "14 h ago"; owner: E08-D06). */
export function ago(ms: number): string {
  const s = Math.max(Math.floor(ms / 1000), 0);
  if (s < 60) return `${String(s)} s ago`;
  if (s < 3600) return `${String(Math.floor(s / 60))} min ago`;
  return `${String(Math.floor(s / 3600))} h ago`;
}
export const checked = (ms: number): string => `checked ${ago(ms)}`;
export const overdue = (ms: number): string =>
  `Instrument list updated ${ago(ms)} — the scheduled refresh is overdue.`;
export const DEMO_LIVE_CATALOGUE = "Bybit live catalogue";

/** D06 §4.4. */
export const TIERS_UNAVAILABLE = "Risk-limit tiers: not available yet";
export const tiersCaption = (symbol: string): string => `Risk-limit tiers for ${symbol}`;
export const showAllTiers = (total: number): string => `Show all ${String(total)} tiers`;
export const TIERS_SCROLL_LABEL = "Risk-limit tiers, scrollable";

/** D06 §6 / D13 `d06.rules-changed-while-open.*`. */
export const wasText = (was: string): string => `Changed · was ${was}`;
export const rulesChangedAt = (time: string, from: number, to: number): string =>
  `Rules changed at ${time} UTC (revision ${String(from)} → ${String(to)}).`;
export const rulesChangedSentence = (
  label: string,
  now: string,
  unit: string | null,
  was: string,
) =>
  `Contract rules changed: ${label} is now ${now}${unit === null ? "" : ` ${unit}`}, was ${was}.`;

/** D06 §6 not trading, D13 `d06.not-trading.*`. */
export const notTrading = (symbol: string): string => `${symbol} is not trading on Bybit.`;
export const preLaunch = (symbol: string): string =>
  `${symbol} is not open for trading in CandleViewer — pre-launch on Bybit.`;
export const noLiveTradingData = (symbol: string): string =>
  `No live trading data — ${symbol} is not trading.`;
export const NO_COVERAGE_NOT_TRADING =
  "Recorded coverage isn't available for symbols that aren't trading.";
export const STATUS_FALLBACK = {
  Closed: "Status: Closed.",
  Delivering: "Status: Delivering.",
  PreLaunch: "Not trading yet — status: Pre-launch.",
} as const;
export const noFunding = (symbol: string): string => `No funding — ${symbol} is not trading.`;

/** D06 §6 catalogue loading, contract load failed (D-12), not listed, forbidden. */
export const checkingBybit = (symbol: string): string => `Checking Bybit for ${symbol}…`;
export const loadingList = (s: number): string =>
  `CandleViewer's server is loading the instrument list from Bybit — next try in ${String(s)} s.`;
export const COVERAGE_WAITS = "Recorded coverage waits for the instrument list.";
export const loadFailed = (symbol: string): string => `Couldn't load ${symbol}'s contract rules.`;
export const CAUSE_NETWORK = "CandleViewer can't reach its server.";
export const CAUSE_UNAVAILABLE = "The server still has no list from Bybit after a minute.";
export const causeAnswered = (status: number): string =>
  `CandleViewer's server answered ${String(status)}.`;
export const reference = (instance: string): string => `Ref ${instance}`;
/** The order line (D06 §6, until CR-10 ships). */
export const orderLine = (symbol: string): string =>
  `CandleViewer can't check ${symbol} orders against these rules until they load.`;
export const notInList = (symbol: string): string =>
  `${symbol} isn't in Bybit's instrument list as CandleViewer last read it.`;
export const FORBIDDEN = "Your role can't see instruments.";
export const COVERAGE_FAILED = "Couldn't load recorded coverage.";

/** D06 §4.3: the coverage rows. */
export const coverageAsOf = (time: string): string => `Coverage as of ${time} UTC`;
export const IMPORTED_DAYS = "trades can include imported days";
export const NO_RECORDED_DATA = "No recorded data in the last 90 days";
export const STREAM_WORDS = { trades: "trades", orderbook: "order book" } as const;
export const streamFrom = (stream: string, date: string): string => `${stream} from ${date}`;
export const GAP_REASONS: Readonly<Record<string, string>> = {
  ws_disconnect: "connection lost",
  backend_restart: "CandleViewer restarted",
  retention_purge: "removed by the retention policy",
  exchange_outage: "exchange outage",
  never_recorded: "not recorded",
  backpressure_drop: "rows dropped under write pressure",
  seq_jump: "order-book sequence jump",
};
export const GAP_UNKNOWN = "a gap";

/** D06 §6 stale states, D13 `d06.stale-*`, `d06.exchange-feed-down`, `d06.reconnecting-disconnected`. */
export const staleT1 = (duration: string): string => `Stale ${duration}`;
export const lastUpdate = (time: string): string => `Last update ${time} UTC`;
export const staleT2 = (symbol: string, duration: string): string =>
  `Stale ${duration} — new orders blocked on ${symbol}`;
export const staleServer = (time: string): string => `Stale (server) — since ${time}`;
export const FEED_DOWN = "Stale — exchange feed down";
export const disconnected = (time: string): string => `Disconnected — last data ${time}`;
export const NO_LIVE_VALUES = "No live values yet";
export const LIVE_UNAVAILABLE = [
  "Live values unavailable — CandleViewer has reached its live-data limit.",
  "Close a chart or a watchlist symbol, then try again.",
] as const;
export const LIVE_STALE = "Live values stale.";
export const LIVE_CURRENT = "Live values current.";

/** D06 §7: the funding countdown. */
export const NEXT_FUNDING_UNKNOWN = "Next funding time not available";
export const SETTLEMENT_PASSED = "Settlement time passed — waiting for an update";
export const nextIn = (clock: string, at: string): string => `next in ${clock} · ${at} UTC`;
export const settlesIn = (clock: string, at: string): string => `settles in ${clock} · ${at} UTC`;
export const clockAlarmAt = (at: string, about: string): string =>
  `at ${at} UTC (in about ${about})`;
export const clockSkew = (ms: number): string =>
  `Clock skew ${String(ms)} ms — the countdown may be off`;
export const fundingSpokenName = (about: string, at: string): string =>
  `Next funding in ${about}, at ${at} UTC`;
export const fundingSpoken = (symbol: string, minutes: number): string =>
  `${symbol} funding settles in ${String(minutes)} ${minutes === 1 ? "minute" : "minutes"}.`;
