/**
 * The E16-D05 §14 deck (mirrored in E16-D06's copy JSON), the keys this slice shows, verbatim. Nothing here is composed past
 * its fills; the `rbac.*` sentences are `packages/ui`'s registry (E09-D09 §3.1), never restated. Every timestamp is UTC
 * text (D06 C-x). The coverage-failed words are G-09's gap: the nearest merged string (`symbol-info` `COVERAGE_FAILED`).
 * Gap ranges are `symbol-info` `gapText`'s words.
 */
import { COVERAGE_FAILED } from "../symbol-info/copy";

export const fill = (text: string, values: Readonly<Record<string, string>>): string =>
  text.replace(/\{(\w+)\}/g, (match, name: string) => values[name] ?? match);

export const HEADING = {
  history_starts: "History starts {ts} — recording began then.",
  not_recorded: "History starts when you record {symbol} — recording has not begun yet.",
  no_bars_between: "No bars for {symbol} {interval} between {from} and {to} UTC.",
  no_bars_window: "No bars for {symbol} {interval} in this window.",
  retention_trimmed: "{symbol} history before {date} was removed by the retention policy.",
  not_trading: "{symbol} is not trading on Bybit.",
  no_history_here: "No history is available for {symbol} here.",
} as const;

export const CAUSE = {
  recorded_only: "Nothing is missing or broken: CandleViewer keeps only what it records.",
  no_trades: "No trades were recorded in this window.",
  restricted: "Recording status restricted",
  no_live: "No live data will arrive.",
} as const;

/** `empty.gap.*`: the cause sentence per `gaps[].reason` (D05 §2; 8 sentences with the fallback). */
export const GAP_SENTENCE: Readonly<Record<string, string>> = {
  ws_disconnect: "Recording was interrupted (connection to the exchange lost).",
  backend_restart: "Recording was interrupted (CandleViewer restarted).",
  exchange_outage: "Recording was interrupted (exchange outage).",
  backpressure_drop: "Recording dropped data while the disk was under pressure.",
  seq_jump: "Recording lost order-book updates (sequence gap).",
  retention_purge: "Older data was removed by the retention policy ({N} days).",
};
/** The deck's fallback cause sentence for a reason this client does not know (C-6.3). */
export const GAP_UNKNOWN = "Recording gap.";

/** `empty.cause.not_trading_status`: E11-D04 :798's words per `Instrument.status`. */
export const STATUS_WORDS: Readonly<Record<string, string>> = {
  Closed: "Status: Closed.",
  Delivering: "Status: Delivering.",
  PreLaunch: "Not trading yet — status: Pre-launch.",
};
/** An unlisted status with no `status_reason`: PROPOSED (a C-row to E16-D05; D05 :184 lists three). */
export const STATUS_FALLBACK = "Status: {status}.";

export const LABEL = {
  record: "Record this symbol",
  go_recorded: "Go to recorded history",
  go_latest: "Go to latest",
  open_symbol: "Open symbol info",
  learn_more: "Learn more",
  show_coverage: "Show coverage",
  switch_symbol: "Switch symbol",
  retention_policy: "Retention policy",
  retry: "Retry",
} as const;

export const LIVE = {
  live: "Live data is streaming now.",
  delayed: "Live data is streaming at a reduced rate.",
  disconnected: "Live data will resume when the connection returns.",
} as const;

/** Both carriers of a failed coverage read (the CMP-026 error, the region description) reuse this (BQ-06 (a)). */
export const COVERAGE_ERROR = COVERAGE_FAILED;

/** `chip.partial.missing`: the ranges are `symbol-info` `gapText`'s words (one implementation). */
export const GAP_MISSING = "Missing: {ranges}.";
/** `gap.tooltip.backfilled`: PROPOSED until `22` serves `gaps[].backfilled` (D05-G1; BQ-04). */
export const GAP_BACKFILLED = "Bars from exchange klines; order flow missing.";

/** The verb `rbac.owner_only` takes for `recording:write` (E09-D09 §3.2; D05-C8). */
export const RECORD_VERB = "change recording";
