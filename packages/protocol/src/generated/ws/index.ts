// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with `pnpm --filter @candleviewer/protocol generate`.
// Source: docs/plan/ws-schema.json, extracted from docs/plan/23-ws-protocol.md
// §13-15. Hand edits are rejected by the header-guard lint
// (packages/protocol/scripts/check-generated-guard.mjs) and by
// `linguist-generated` in .gitattributes.
// ==========================================================================
/* eslint-disable */

// Source: cv://ws/v1/alerts.schema.json
export interface Alerts {
  deliveries: {
    id: number;
    alert_id: string;
    channel: "in_app" | "email" | "webhook" | "push" | "desktop";
    status: "queued" | "sent" | "failed" | "suppressed" | "acked";
    severity?: "debug" | "info" | "warning" | "error" | "critical";
    title?: string;
    message: string;
    symbol?: string | null;
    /**
     * Epoch milliseconds, UTC.
     */
    fired_at_ms: number;
    acked_at_ms?: number | null;
    error?: string | null;
  }[];
  unacked_count?: number;
}

// Source: cv://ws/v1/auth.schema.json
export interface CvWsV1AuthSchemaJson {
  access_token: string;
  /**
   * Environments this connection intends to observe; intersected with the token's grants.
   */
  environments?: ("live" | "demo" | "testnet")[];
}

// Source: cv://ws/v1/auth_ok.schema.json
export interface CvWsV1AuthOkSchemaJson {
  user_id: string;
  username?: string;
  /**
   * Items: Closed set: OpenAPI RoleName / role_name enum (22-api-openapi.yaml) and CONSTITUTION C-12.4 (Owner, Manager, Viewer); custom roles are out of scope for v1.
   */
  roles: ("owner" | "manager" | "viewer")[];
  permissions: string[];
  account_scope: string[];
  allowed_environments?: ("live" | "demo" | "testnet")[];
  session_id: string;
  /**
   * Epoch milliseconds, UTC.
   */
  token_expires_at_ms: number;
  kill_switch?: KillSwitch;
}
export interface KillSwitch {
  engaged: boolean;
  scope: "global" | "accounts";
  exchange_account_ids?: string[];
  engaged_at_ms?: number | null;
  engaged_by?: string | null;
  engaged_by_username?: string | null;
  reason?: string | null;
}

// Source: cv://ws/v1/bars.schema.json
export interface BarsSymbolBarTypeParam {
  symbol: string;
  bar_type: "time" | "tick" | "volume" | "range" | "delta" | "renko" | "pnf" | "heikin_ashi";
  param: string;
  bars: {
    /**
     * ADR-0033 series generation (= epoch); 0 until ratified. Part of the coalescing key (§8.2).
     */
    generation: number;
    /**
     * Bar index, strictly increasing within a generation; with generation, the coalescing key (§8.2). t_ms may repeat for non-time bars.
     */
    index: number;
    /**
     * Bar open time.
     */
    t_ms: number;
    /**
     * Present for non-time bars.
     */
    close_t_ms?: number;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    o: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    h: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    l: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    c: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    v: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    turnover?: string;
    trades?: number;
    /**
     * False for the in-progress bar. A client MUST NOT treat it as closed.
     */
    confirm: boolean;
    /**
     * Optional. True when a late trade re-closed an already-confirmed bar at this (generation, index); the client replaces the stored bar by key and re-renders (§8.2). Structured payloads only; binary records carry no amended bit.
     */
    amended?: boolean;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    delta?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    cvd?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    min_delta?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    max_delta?: string;
  }[];
  coalesced?: boolean;
  coalesced_count?: number;
}

// Source: cv://ws/v1/book.schema.json
/**
 * Descending by price. Size "0" deletes the level.
 */
export type Levels = [string, string][];
/**
 * Ascending by price. Size "0" deletes the level.
 */
export type Levels1 = [string, string][];
/**
 * This interface was referenced by `BookSymbolDepth`'s JSON-Schema
 * via the `definition` "levels".
 */
export type Levels2 = [string, string][];

export interface BookSymbolDepth {
  symbol: string;
  depth?: 1 | 50 | 200 | 500;
  price_scale?: number;
  qty_scale?: number;
  /**
   * Bybit orderbook update id `u`, for diagnostics only.
   */
  xu?: number;
  /**
   * Bybit cross-topic sequence `seq`.
   */
  xseq?: number;
  bids: Levels;
  asks: Levels1;
  stale?: boolean;
  coalesced?: boolean;
  coalesced_count?: number;
}

// Source: cv://ws/v1/bye.schema.json
export interface CvWsV1ByeSchemaJson {
  code: 1000 | 1001 | 1002 | 1009 | 1011 | 1013 | 4400 | 4401 | 4403 | 4429;
  reason: string;
  message: string;
  retry_after_ms?: number;
  reconnect?: boolean;
  hint?: {
    /**
     * @maxItems 5
     */
    most_expensive_topics?:
      | []
      | [string]
      | [string, string]
      | [string, string, string]
      | [string, string, string, string]
      | [string, string, string, string, string];
  };
}

// Source: cv://ws/v1/common.schema.json
/**
 * Arbitrary-precision decimal as a string; never a JSON number.
 *
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "decimal".
 */
export type Decimal = string;
/**
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "symbol".
 */
export type Symbol = string;
/**
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "uuid".
 */
export type Uuid = string;
/**
 * Epoch milliseconds, UTC.
 *
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "epochMs".
 */
export type EpochMs = number;
/**
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "seq".
 */
export type Seq = number | null;
/**
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "topic".
 */
export type Topic = string;
/**
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "environment".
 */
export type Environment = "live" | "demo" | "testnet";
/**
 * True when the fill/order came from the paper matcher rather than the exchange. Mirrors the `is_paper` column.
 *
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "isPaper".
 */
export type IsPaper = boolean;
/**
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "side".
 */
export type Side = "buy" | "sell";
/**
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "barType".
 */
export type BarType =
  "time" | "tick" | "volume" | "range" | "delta" | "renko" | "pnf" | "heikin_ashi";
/**
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "depth".
 */
export type Depth = 1 | 50 | 200 | 500;
/**
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "errorCode".
 */
export type ErrorCode =
  | "protocol_violation"
  | "frame_malformed"
  | "unsupported_protocol"
  | "not_authenticated"
  | "auth_failed"
  | "auth_timeout"
  | "token_expired"
  | "user_disabled"
  | "forbidden"
  | "account_scope_denied"
  | "unknown_topic"
  | "invalid_topic_format"
  | "unsupported_symbol"
  | "invalid_options"
  | "encoding_unsupported"
  | "subscription_limit"
  | "too_many_topics"
  | "duplicate_subscription"
  | "not_subscribed"
  | "resync_rate_limited"
  | "client_rate_limited"
  | "slow_consumer"
  | "no_data_recorded"
  | "degraded_data"
  | "exchange_unavailable"
  | "replay_session_not_found"
  | "replay_session_ended"
  | "internal_error";

export interface CandleViewerWSSharedDefinitions {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "error".
 */
export interface Error {
  code: ErrorCode;
  message: string;
  retryable?: boolean;
  field?: string;
  request_id?: string;
  close?: boolean;
}
/**
 * This interface was referenced by `CandleViewerWSSharedDefinitions`'s JSON-Schema
 * via the `definition` "snapMeta".
 */
export interface SnapMeta {
  reason?:
    | "initial"
    | "client_resync"
    | "upstream_desync"
    | "upstream_reconnect"
    | "backpressure"
    | "reconfigure"
    | "instrument_revision"
    | "replay_seek";
  previous_seq?: Seq;
  recording_started_at_ms?: EpochMs;
  history_bars?: number;
  source?: "live" | "replay";
}

// Source: cv://ws/v1/ctl.schema.json
export interface CvWsV1CtlSchemaJson {
  throttle_ms?: number;
  coalesce?: boolean;
  depth?: 1 | 50 | 200 | 500;
  price_grouping?: number;
  metrics?: string[];
  /**
   * Arbitrary-precision decimal as a string; never a JSON number.
   */
  min_size?: string;
  /**
   * Re-derived bucket (§6.1.1); triggers `resnapshot: true`.
   */
  time_bucket_ms?: 100 | 250 | 500 | 1000 | 5000;
  /**
   * Client-side pause; the server stops emitting but keeps state.
   */
  paused?: boolean;
}

// Source: cv://ws/v1/ctl_ok.schema.json
export interface CvWsV1CtlOkSchemaJson {
  effective: {
    [k: string]: unknown;
  };
  /**
   * When true, a fresh `snap` follows and prior state must be discarded.
   */
  resnapshot?: boolean;
}

// Source: cv://ws/v1/envelope.schema.json
export type CandleViewerWSEnvelope = {
  t:
    | "hello"
    | "welcome"
    | "auth"
    | "auth_ok"
    | "sub"
    | "sub_ok"
    | "unsub"
    | "unsub_ok"
    | "snap"
    | "d"
    | "resync"
    | "revoked"
    | "permission_change"
    | "ping"
    | "pong"
    | "err"
    | "ctl"
    | "ctl_ok"
    | "bye";
  /**
   * Correlation id; echoed on replies.
   */
  id?: string;
  ch?: string;
  s?: number | null;
  /**
   * Epoch milliseconds, UTC.
   */
  ts?: number;
  /**
   * Epoch milliseconds, UTC.
   */
  wt?: number;
  /**
   * Replay session id; present only on replay frames.
   */
  rs?: string;
  e?: "j" | "b" | "b64";
  meta?: SnapMeta;
  p?: unknown;
};

export interface SnapMeta {
  reason?:
    | "initial"
    | "client_resync"
    | "upstream_desync"
    | "upstream_reconnect"
    | "backpressure"
    | "reconfigure"
    | "instrument_revision"
    | "replay_seek";
  previous_seq?: number | null;
  /**
   * Epoch milliseconds, UTC.
   */
  recording_started_at_ms?: number;
  history_bars?: number;
  source?: "live" | "replay";
}

// Source: cv://ws/v1/executions.schema.json
export interface Executions {
  executions: {
    id: string;
    /**
     * Exchange fill id; unique, used for dedupe.
     */
    exec_id: string;
    order_id: string;
    exchange_account_id: string;
    trade_group_id?: string | null;
    symbol: string;
    side: "buy" | "sell";
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    exec_qty: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    exec_price: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    exec_value?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    fee?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    fee_rate?: string;
    fee_coin?: string;
    is_maker?: boolean;
    exec_type?: "Trade" | "AdlTrade" | "Funding" | "BustTrade" | "Settle";
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    exec_pnl?: string;
    environment?: "live" | "demo" | "testnet";
    /**
     * True when the fill/order came from the paper matcher rather than the exchange. Mirrors the `is_paper` column.
     */
    is_paper?: boolean;
    /**
     * Epoch milliseconds, UTC.
     */
    ts_ms: number;
  }[];
}

// Source: cv://ws/v1/footprint.schema.json
export interface FootprintSymbolBarTypeParam {
  symbol: string;
  bar_type: "time" | "tick" | "volume" | "range" | "delta" | "renko" | "pnf" | "heikin_ashi";
  param: string;
  /**
   * Arbitrary-precision decimal as a string; never a JSON number.
   */
  tick_size?: string;
  price_grouping?: number;
  bars: {
    /**
     * Epoch milliseconds, UTC.
     */
    t_ms: number;
    /**
     * Epoch milliseconds, UTC.
     */
    close_t_ms?: number;
    confirm?: boolean;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    poc_price?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    value_area_high?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    value_area_low?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    delta?: string;
    unfinished_auction?: {
      high?: boolean;
      low?: boolean;
    };
    cells: {
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      price: string;
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      bid_volume: string;
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      ask_volume: string;
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      delta?: string;
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      total_volume?: string;
      trades?: number;
      is_poc?: boolean;
    }[];
    imbalances?: {
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      price: string;
      direction: "buy" | "sell";
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      ratio: string;
      stacked?: boolean;
      stack_size?: number;
      estimated?: boolean;
    }[];
  }[];
  coalesced?: boolean;
  coalesced_count?: number;
}

// Source: cv://ws/v1/heartbeat.schema.json
export interface PingPongPayloads {
  /**
   * Epoch milliseconds, UTC.
   */
  client_ms?: number;
  /**
   * Epoch milliseconds, UTC.
   */
  server_ms?: number;
  rtt_hint_ms?: number;
}

// Source: cv://ws/v1/heatmap.schema.json
export interface HeatmapSymbol {
  symbol: string;
  /**
   * Effective bucket in force, echoing what the client derived per §6.1.1 (or 500 if the client sent none).
   */
  time_bucket_ms: 100 | 250 | 500 | 1000 | 5000;
  price_grouping?: number;
  depth?: 1 | 50 | 200 | 500;
  columns: {
    /**
     * Epoch milliseconds, UTC.
     */
    t_ms: number;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    price_min: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    price_step: string;
    /**
     * Resting bid size per price row, ascending from `price_min`.
     */
    bids: number[];
    asks: number[];
    /**
     * False while the time bucket is still accumulating.
     */
    complete?: boolean;
  }[];
  max_value?: number;
  estimated?: boolean;
  coalesced?: boolean;
  coalesced_count?: number;
}

// Source: cv://ws/v1/hello.schema.json
export interface CvWsV1HelloSchemaJson {
  client: string;
  client_version: string;
  shell?: "electron" | "browser" | "other";
  protocol: "cv.v1";
  encodings?: ("binary" | "structured")[];
  capabilities?: (
    | "binary_book"
    | "binary_bars"
    | "binary_trades"
    | "binary_footprint"
    | "binary_heatmap"
    | "coalescing"
    | "replay"
    | "partial_snapshots"
  )[];
  locale?: string;
  /**
   * Epoch milliseconds, UTC.
   */
  clock_ms?: number;
}

// Source: cv://ws/v1/liquidations.schema.json
export interface LiquidationsSymbolLiquidations {
  liquidations: {
    symbol: string;
    /**
     * Epoch milliseconds, UTC.
     */
    ts_ms: number;
    side: "buy" | "sell";
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    price: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    size: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    notional_usd?: string;
    cluster_size?: number;
  }[];
  /**
   * Bybit batches at most one allLiquidation push per symbol per 500 ms; counts are lower bounds.
   */
  note?: string;
}

// Source: cv://ws/v1/metrics.schema.json
export interface MetricsSymbol {
  symbol: string;
  bar_type?: "time" | "tick" | "volume" | "range" | "delta" | "renko" | "pnf" | "heikin_ashi";
  param?: string;
  series: {
    metric:
      | "cvd"
      | "delta"
      | "min_max_delta"
      | "trades_per_sec"
      | "volume_per_sec"
      | "book_updates_per_sec"
      | "tape_acceleration"
      | "imbalance_ratio"
      | "absorption"
      | "exhaustion"
      | "iceberg"
      | "stop_run"
      | "adx"
      | "atr"
      | "hurst"
      | "regime"
      | "vwap"
      | "open_interest_delta"
      | "funding_basis"
      | "liquidation_intensity";
    /**
     * Epoch milliseconds, UTC.
     */
    t_ms: number;
    v: string | null;
    unit?: "base_volume" | "index" | "ratio" | "confidence" | "usd" | "price" | "count";
    /**
     * True for heuristic metrics (iceberg, stop_run, absorption, exhaustion).
     */
    estimated?: boolean;
    params?: {
      [k: string]: unknown;
    };
    /**
     * Event detail for event-like metrics, e.g. {price, side, reloads}.
     */
    meta?: {
      [k: string]: unknown;
    };
  }[];
  coalesced?: boolean;
  coalesced_count?: number;
}

// Source: cv://ws/v1/orders.schema.json
export interface Orders {
  orders: {
    id: string;
    exchange_account_id: string;
    trade_group_id?: string | null;
    trade_group_leg_id?: string | null;
    parent_order_id?: string | null;
    order_link_id?: string;
    exchange_order_id?: string | null;
    symbol: string;
    side?: "buy" | "sell";
    order_type?: "market" | "limit";
    intent?:
      | "entry"
      | "stop_loss"
      | "take_profit"
      | "scale_in"
      | "scale_out"
      | "flatten"
      | "reverse"
      | "algo_child";
    state:
      | "new"
      | "pending_submit"
      | "submitted"
      | "accepted"
      | "partially_filled"
      | "filled"
      | "pending_cancel"
      | "cancelled"
      | "pending_amend"
      | "rejected"
      | "expired"
      | "untracked";
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    qty?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    filled_qty?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    remaining_qty?: string;
    price?: string | null;
    avg_fill_price?: string | null;
    time_in_force?: "GTC" | "IOC" | "FOK" | "PostOnly";
    reduce_only?: boolean;
    close_on_trigger?: boolean;
    position_idx?: 0 | 1 | 2;
    trigger_price?: string | null;
    trigger_by?: "LastPrice" | "MarkPrice" | "IndexPrice" | null;
    trigger_direction?: "rise" | "fall" | null;
    take_profit?: string | null;
    stop_loss?: string | null;
    tpsl_mode?: "Full" | "Partial";
    algo_kind?: "none" | "oco" | "iceberg" | "twap" | "chase" | "scaled" | "bracket";
    environment?: "live" | "demo" | "testnet";
    /**
     * True when the fill/order came from the paper matcher rather than the exchange. Mirrors the `is_paper` column.
     */
    is_paper?: boolean;
    rejected_reason?: string | null;
    /**
     * What caused this frame; drives UI animation and the order-timeline widget.
     */
    change?:
      | "created"
      | "submitted"
      | "ack"
      | "fill"
      | "amend"
      | "cancel"
      | "reject"
      | "expire"
      | "reconcile";
    /**
     * Epoch milliseconds, UTC.
     */
    updated_at_ms: number;
  }[];
  /**
   * Order ids that left the open set (terminal state) and may be dropped from the live view.
   */
  removed?: string[];
}

// Source: cv://ws/v1/permission_change.schema.json
export interface CvWsV1PermissionChangeSchemaJson {
  user_id: string;
  /**
   * Items: Closed set: OpenAPI RoleName / role_name enum (22-api-openapi.yaml) and CONSTITUTION C-12.4 (Owner, Manager, Viewer); custom roles are out of scope for v1.
   */
  roles: ("owner" | "manager" | "viewer")[];
  permissions: string[];
  account_scope: string[];
}

// Source: cv://ws/v1/positions.schema.json
export interface Positions {
  positions: {
    id: string;
    exchange_account_id: string;
    symbol: string;
    side: "long" | "short" | "flat";
    position_idx?: 0 | 1 | 2;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    size: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    avg_price?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    mark_price?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    position_value?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    leverage?: string;
    margin_mode?: "cross" | "isolated" | "portfolio";
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    unrealised_pnl?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    realised_pnl_session?: string;
    liq_price?: string | null;
    bust_price?: string | null;
    take_profit?: string | null;
    stop_loss?: string | null;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    trailing_stop?: string;
    tpsl_mode?: "Full" | "Partial";
    /**
     * False violates the safety invariant (arch P4); the OMS re-asserts the stop and raises a critical alert.
     */
    native_stop_present?: boolean;
    trade_group_id?: string | null;
    r_multiple?: string | null;
    environment?: "live" | "demo" | "testnet";
    /**
     * True when the fill/order came from the paper matcher rather than the exchange. Mirrors the `is_paper` column.
     */
    is_paper?: boolean;
    /**
     * Epoch milliseconds, UTC.
     */
    updated_at_ms: number;
  }[];
  /**
   * Positions that went flat; applied after this frame's `positions` upserts.
   */
  removed?: string[];
  coalesced?: boolean;
  coalesced_count?: number;
}

// Source: cv://ws/v1/profile.schema.json
export interface ProfileSymbolKind {
  symbol: string;
  kind: "volume" | "delta" | "tpo";
  split?: "composite" | "session" | "fixed";
  profiles: {
    /**
     * Epoch milliseconds, UTC.
     */
    period_start_ms: number;
    /**
     * Epoch milliseconds, UTC.
     */
    period_end_ms?: number;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    total_volume?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    poc_price?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    value_area_high?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    value_area_low?: string;
    naked_poc?: boolean;
    rows: {
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      price: string;
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      volume: string;
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      buy_volume?: string;
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      sell_volume?: string;
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      delta?: string;
      tpo_count?: number;
    }[];
    /**
     * Items: Arbitrary-precision decimal as a string; never a JSON number.
     */
    hvn?: string[];
    /**
     * Items: Arbitrary-precision decimal as a string; never a JSON number.
     */
    lvn?: string[];
  }[];
}

// Source: cv://ws/v1/recorder.schema.json
export interface Recorder {
  overall: "healthy" | "degraded" | "warning" | "down";
  connections?: {
    endpoint?: string;
    state?: "connecting" | "connected" | "degraded" | "disconnected";
    subscribed_topics?: number;
    reconnects_last_hour?: number;
    last_ping_ms?: number;
  }[];
  symbols: {
    symbol: string;
    state: "idle" | "starting" | "recording" | "degraded" | "stopping" | "stopped" | "error";
    reason?: "manual" | "chart_open" | "position_open" | "rule_dependency" | "alert_dependency";
    pinned?: boolean;
    lag_ms?: number;
    rows_last_hour?: number;
    /**
     * Non-zero is an incident, not a warning.
     */
    dropped_messages?: number;
    resyncs_last_hour?: number;
    disk_bytes?: number;
    /**
     * Epoch milliseconds, UTC.
     */
    last_event_at_ms?: number;
  }[];
  ingest_rate_msgs_per_sec?: number;
  write_backlog_rows?: number;
  storage?: {
    disk_free_bytes?: number;
    daily_growth_bytes?: number;
    projected_full_at_ms?: number | null;
  };
}

// Source: cv://ws/v1/resync.schema.json
export interface CvWsV1ResyncSchemaJson {
  last_seq?: number | null;
  reason: "sequence_gap" | "decode_error" | "state_corrupt" | "client_restart" | "manual";
}

// Source: cv://ws/v1/revoked.schema.json
export interface CvWsV1RevokedSchemaJson {
  reason:
    | "permission_revoked"
    | "account_scope_changed"
    | "user_disabled"
    | "session_revoked"
    | "key_revoked"
    | "account_disabled"
    | "replay_session_ended"
    | "resync_rate_limited"
    | "topic_removed";
  message: string;
  removed_accounts?: string[];
  resubscribe_allowed?: boolean;
}

// Source: cv://ws/v1/rules.schema.json
export interface Rules {
  rules?: {
    id: string;
    name?: string;
    mode: "disabled" | "simulate" | "armed";
    active_version_id?: string | null;
    version?: number;
    last_run_status?: "running" | "ok" | "error" | "aborted" | "throttled" | null;
    fire_count_24h?: number;
    /**
     * Set while a cooldown guard is active.
     */
    next_eligible_fire_at_ms?: number | null;
    /**
     * Epoch milliseconds, UTC.
     */
    updated_at_ms: number;
  }[];
  /**
   * Present only when subscribed with include_events: true.
   */
  events?: {
    rule_id: string;
    run_id: string;
    kind:
      | "evaluated"
      | "suppressed"
      | "action_sent"
      | "action_result"
      | "error"
      | "started"
      | "finished";
    /**
     * Epoch milliseconds, UTC.
     */
    ts_ms: number;
    payload?: {
      [k: string]: unknown;
    };
  }[];
}

// Source: cv://ws/v1/sub.schema.json
export interface CvWsV1SubSchemaJson {
  /**
   * @minItems 1
   * @maxItems 50
   */
  topics: [
    {
      ch: string;
      opts?: Options;
    },
    ...{
      ch: string;
      opts?: Options;
    }[],
  ];
  snapshot?: boolean;
  replay_session_id?: string | null;
}
/**
 * Union of universal and topic-specific options. Unknown keys are rejected with `invalid_options`.
 *
 * This interface was referenced by `CvWsV1SubSchemaJson`'s JSON-Schema
 * via the `definition` "options".
 */
export interface Options {
  throttle_ms?: number;
  encoding?: "binary" | "structured";
  coalesce?: boolean;
  from_seq?: number | null;
  /**
   * Epoch milliseconds, UTC.
   */
  from_ts_ms?: number;
  /**
   * Arbitrary-precision decimal as a string; never a JSON number.
   */
  min_size?: string;
  cluster_window_ms?: number;
  cluster_tolerance_ticks?: number;
  include_delta?: boolean;
  history?: number;
  price_grouping?: number;
  imbalance_ratio?: number;
  min_stack?: number;
  /**
   * Arbitrary-precision decimal as a string; never a JSON number.
   */
  min_imbalance_volume?: string;
  /**
   * Client SHOULD derive this per §6.1.1 rather than sending a constant; 500 is the non-visual-client fallback.
   */
  time_bucket_ms?: 100 | 250 | 500 | 1000 | 5000;
  depth?: 1 | 50 | 200 | 500;
  window_seconds?: number;
  split?: "composite" | "session" | "fixed";
  session_anchor?: "utc_day" | "funding_8h" | "custom";
  value_area_pct?: number;
  /**
   * @minItems 1
   * @maxItems 12
   */
  metrics?:
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ];
  bar_type?: "time" | "tick" | "volume" | "range" | "delta" | "renko" | "pnf" | "heikin_ashi";
  param?: string;
  params?: {
    [k: string]: unknown;
  };
  /**
   * @maxItems 25
   */
  exchange_account_ids?: string[];
  /**
   * @maxItems 40
   */
  symbols?: string[];
  open_only?: boolean;
  status?: string[];
  rule_ids?: string[];
  include_events?: boolean;
  unacked_only?: boolean;
  /**
   * Arbitrary-precision decimal as a string; never a JSON number.
   */
  min_notional_usd?: string;
}

// Source: cv://ws/v1/sub_ok.schema.json
export interface CvWsV1SubOkSchemaJson {
  results: {
    ch: string;
    ok: boolean;
    sub_id?: string;
    snapshot_pending?: boolean;
    snapshot_forced?: boolean;
    effective?: {
      [k: string]: unknown;
    };
    warning?: Error;
    error?: Error;
  }[];
}
export interface Error {
  code:
    | "protocol_violation"
    | "frame_malformed"
    | "unsupported_protocol"
    | "not_authenticated"
    | "auth_failed"
    | "auth_timeout"
    | "token_expired"
    | "user_disabled"
    | "forbidden"
    | "account_scope_denied"
    | "unknown_topic"
    | "invalid_topic_format"
    | "unsupported_symbol"
    | "invalid_options"
    | "encoding_unsupported"
    | "subscription_limit"
    | "too_many_topics"
    | "duplicate_subscription"
    | "not_subscribed"
    | "resync_rate_limited"
    | "client_rate_limited"
    | "slow_consumer"
    | "no_data_recorded"
    | "degraded_data"
    | "exchange_unavailable"
    | "replay_session_not_found"
    | "replay_session_ended"
    | "internal_error";
  message: string;
  retryable?: boolean;
  field?: string;
  request_id?: string;
  close?: boolean;
}

// Source: cv://ws/v1/system.schema.json
export interface System {
  kind:
    | "health"
    | "kill_switch"
    | "feature_flags"
    | "exchange_state"
    | "connection_quality"
    | "shutdown_notice"
    | "degraded_data"
    | "clock_drift"
    | "notice";
  severity?: "debug" | "info" | "warning" | "error" | "critical";
  message?: string;
  health?: "healthy" | "degraded" | "warning" | "down";
  components?: {
    name?: string;
    state?: "healthy" | "degraded" | "warning" | "down";
    detail?: string;
  }[];
  kill_switch?: KillSwitch;
  actions?: {
    orders_cancelled?: number;
    positions_flattened?: number;
    rules_disarmed?: number;
  };
  feature_flags?: {
    [k: string]: unknown;
  };
  exchange?: {
    public_ws?: "connected" | "connecting" | "resyncing" | "disconnected";
    private_ws?: "connected" | "connecting" | "resyncing" | "disconnected";
    rest?: "healthy" | "degraded" | "rate_limited" | "down";
    rate_budget_free_pct?: number;
  };
  public_ws?: "connected" | "connecting" | "resyncing" | "disconnected";
  private_ws?: "connected" | "connecting" | "resyncing" | "disconnected";
  affected_symbols?: string[];
  class?: "healthy" | "lagging" | "saturated" | "overflowing";
  queue_pct?: number;
  rtt_ms?: number;
  applied?: {
    throttle_multiplier?: number;
    forced_coalesce?: boolean;
    degraded_topics?: string[];
  };
  reason?: string;
  closing_in_ms?: number;
  expected_downtime_ms?: number;
  clock_offset_ms?: number;
  degraded_topics?: string[];
}
/**
 * This interface was referenced by `System`'s JSON-Schema
 * via the `definition` "killSwitch".
 */
export interface KillSwitch {
  engaged: boolean;
  scope: "global" | "accounts";
  exchange_account_ids?: string[];
  engaged_at_ms?: number | null;
  engaged_by?: string | null;
  engaged_by_username?: string | null;
  reason?: string | null;
}

// Source: cv://ws/v1/ticker.schema.json
export interface TickerSymbolTicker {
  tickers: {
    symbol: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    last_price: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    mark_price?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    index_price?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    bid1_price?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    bid1_size?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    ask1_price?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    ask1_size?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    price_change_pct_24h?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    high_24h?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    low_24h?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    volume_24h?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    turnover_24h?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    open_interest?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    open_interest_value?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    funding_rate?: string;
    /**
     * Epoch milliseconds, UTC.
     */
    next_funding_time_ms?: number;
    /**
     * Epoch milliseconds, UTC.
     */
    ts_ms: number;
    stale?: boolean;
  }[];
  coalesced?: boolean;
  coalesced_count?: number;
}

// Source: cv://ws/v1/trade_groups.schema.json
export interface TradeGroups {
  trade_groups: {
    id: string;
    client_group_ref?: string;
    symbol?: string;
    side?: "buy" | "sell";
    intent?: string;
    status:
      | "draft"
      | "submitting"
      | "partially_open"
      | "open"
      | "closing"
      | "closed"
      | "failed"
      | "cancelled";
    atomicity?: "best_effort" | "all_or_none";
    algo_kind?: "none" | "oco" | "iceberg" | "twap" | "chase" | "scaled" | "bracket";
    rule_id?: string | null;
    legs?: {
      id: string;
      exchange_account_id: string;
      account_profile_id?: string | null;
      sequence_no?: number;
      status:
        | "pending"
        | "submitted"
        | "rejected"
        | "open"
        | "partially_filled"
        | "filled"
        | "cancelled"
        | "closed"
        | "error";
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      target_qty?: string;
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      filled_qty?: string;
      avg_entry_price?: string | null;
      avg_exit_price?: string | null;
      native_sl_confirmed?: boolean;
      risk_usd?: string | null;
      realised_pnl?: string | null;
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      fees_paid?: string;
      error?: null | {
        code: string;
        message: string;
        exchange_ret_code?: number | null;
        retryable?: boolean;
      };
    }[];
    totals?: {
      requested_legs?: number;
      submitted_legs?: number;
      rejected_legs?: number;
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      filled_qty?: string;
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      target_qty?: string;
      realised_pnl?: string | null;
    };
    /**
     * Epoch milliseconds, UTC.
     */
    updated_at_ms: number;
  }[];
}

// Source: cv://ws/v1/trades.schema.json
export interface TradesSymbol {
  symbol: string;
  trades: {
    id?: string;
    /**
     * Epoch milliseconds, UTC.
     */
    ts_ms: number;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    price: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    size: string;
    /**
     * Taker/aggressor side, taken directly from Bybit `S`.
     */
    side: "buy" | "sell";
    is_block_trade?: boolean;
    is_liquidation?: boolean;
    cluster_size?: number;
    tick_direction?: "PlusTick" | "ZeroPlusTick" | "MinusTick" | "ZeroMinusTick";
  }[];
  /**
   * Prints filtered out by `min_size` since the previous frame; never silent.
   */
  dropped?: number;
}

// Source: cv://ws/v1/unsub.schema.json
export interface CvWsV1UnsubSchemaJson {
  /**
   * @minItems 1
   * @maxItems 50
   */
  topics: [string, ...string[]];
}

// Source: cv://ws/v1/unsub_ok.schema.json
export interface CvWsV1UnsubOkSchemaJson {
  results: {
    ch: string;
    ok: boolean;
    noop?: boolean;
  }[];
}

// Source: cv://ws/v1/wallet.schema.json
export interface Wallet {
  balances: {
    exchange_account_id: string;
    coin: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    equity: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    wallet_balance?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    available_balance?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    unrealised_pnl?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    realised_pnl_today?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    account_im_rate?: string;
    /**
     * Arbitrary-precision decimal as a string; never a JSON number.
     */
    account_mm_rate?: string;
    /**
     * Live usage against the account profile's risk caps; drives the risk gauge.
     */
    risk_cap_usage?: {
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      daily_loss_usd?: string;
      /**
       * Arbitrary-precision decimal as a string; never a JSON number.
       */
      daily_loss_limit_usd?: string;
      open_positions?: number;
      max_open_positions?: number;
      locked_out_until_ms?: number | null;
    };
    environment?: "live" | "demo" | "testnet";
    /**
     * True when the fill/order came from the paper matcher rather than the exchange. Mirrors the `is_paper` column.
     */
    is_paper?: boolean;
    stale?: boolean;
    /**
     * Epoch milliseconds, UTC.
     */
    updated_at_ms: number;
  }[];
  coalesced?: boolean;
  coalesced_count?: number;
}

// Source: cv://ws/v1/welcome.schema.json
export interface CvWsV1WelcomeSchemaJson {
  protocol: "cv.v1";
  encoding: "msgpack" | "json";
  server_version: string;
  git_sha?: string;
  connection_id: string;
  /**
   * Epoch milliseconds, UTC.
   */
  server_time_ms: number;
  clock_skew_ms?: number;
  auth_required: boolean;
  auth_timeout_ms?: number;
  heartbeat: {
    interval_ms: number;
    timeout_ms: number;
  };
  limits: {
    max_subscriptions: number;
    max_topics_per_request: number;
    max_inbound_frame_bytes: number;
    max_outbound_frame_bytes: number;
    min_throttle_ms: number;
    max_symbols_per_connection?: number;
  };
  features?: {
    [k: string]: boolean;
  };
}

export type WsTopicPayloadMap = {
  "book.{symbol}.{depth}": BookSymbolDepth;
  "trades.{symbol}": TradesSymbol;
  "bars.{symbol}.{bar_type}.{param}": BarsSymbolBarTypeParam;
  "footprint.{symbol}.{bar_type}.{param}": FootprintSymbolBarTypeParam;
  "heatmap.{symbol}": HeatmapSymbol;
  "profile.{symbol}.{kind}": ProfileSymbolKind;
  "metrics.{symbol}": MetricsSymbol;
  "ticker.{symbol}": TickerSymbolTicker;
  "liquidations.{symbol}": LiquidationsSymbolLiquidations;
  orders: Orders;
  positions: Positions;
  executions: Executions;
  wallet: Wallet;
  trade_groups: TradeGroups;
  rules: Rules;
  alerts: Alerts;
  recorder: Recorder;
  system: System;
};
