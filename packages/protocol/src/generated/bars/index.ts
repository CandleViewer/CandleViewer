// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with `pnpm --filter @candleviewer/protocol generate`.
// Source: packages/fixtures/golden/bars/bar-model.schema.json, rendered from
// services/api/candleviewer/bars/models.py by
// services/api/scripts/generate_bar_artifacts.py. Hand edits are rejected by
// the header-guard lint (packages/protocol/scripts/check-generated-guard.mjs).
// ==========================================================================
/* eslint-disable */

export type Qty = string;
export type Px = string;
export type TsUs = number;
export type Notional = string;

/**
 * What series a builder produces. Exactly one per-kind parameter is set, matching `kind`.
 *
 * Identity is `spec_hash` (sha256 over canonical JSON, defaults included) — see
 * `candleviewer.bars.spec`.
 */
export interface BarSpec {
  align_to_epoch?: boolean;
  delta_threshold?: Qty | null;
  interval_ms?: number | null;
  kind: "time" | "tick" | "volume" | "range" | "delta" | "renko";
  price_source?: "last" | "mark";
  range_ticks?: number | null;
  renko_wick?: boolean;
  reversal_bricks?: number;
  session_anchor_utc_min?: number;
  tick_count?: number | null;
  volume_threshold?: Qty | null;
}
/**
 * One bar (§3.1).
 *
 * `min_delta`/`max_delta` are the **running intra-bar path extremes** of the cumulative
 * delta (minimum/maximum the delta reached at any trade inside the bar), NOT the endpoint
 * values and NOT min/max of per-trade deltas. BI-3: `min_delta <= delta <= max_delta`.
 * `synthetic=True` marks a `BarSeries.densify()` filler bar, which is never persisted.
 */
export interface Bar {
  buy_volume: Qty;
  close: Px;
  close_time: TsUs;
  closed: boolean;
  delta: Qty;
  gap_before: boolean;
  high: Px;
  index: number;
  low: Px;
  max_delta: Qty;
  min_delta: Qty;
  open: Px;
  open_time: TsUs;
  partial: boolean;
  sell_volume: Qty;
  spec_hash: string;
  symbol: string;
  synthetic?: boolean;
  tape_gap?: boolean;
  trade_count: number;
  turnover: Notional;
  volume: Qty;
  vwap: Px;
}
/**
 * A builder emission (§3.2).
 */
export interface BarUpdate {
  amended?: boolean;
  bar: Bar;
  kind: "open" | "update" | "close";
}
