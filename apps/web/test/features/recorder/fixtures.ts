/**
 * E16-S01 (BQ-5): the recorder client's fixtures, taken from `docs/plan/22-api-openapi.yaml`'s
 * examples. Each `satisfies` its generated type, so a contract drift fails `typecheck`, and
 * `test/contract/recorderApi.contract.test.ts` reads the same examples out of `22` and compares.
 */
import type { generated } from "@candleviewer/protocol";
import type {
  AddRecordedSymbolBody,
  RecordedSymbolPage,
  RecordingStatus,
  StorageUsage,
} from "../../../src/features/recorder/recorderApi";
import type { RecorderFrame } from "../../../src/features/recorder/recorderTopic";

type Problem = generated.rest.components["schemas"]["Problem"];

/** `listRecordedSymbols` example `two`. */
export const listTwo = {
  items: [
    {
      id: "e1000000-0000-4000-8000-000000000001",
      symbol: "BTCUSDT",
      reason: "manual",
      pinned: true,
      state: "recording",
      streams: ["trades", "orderbook_delta", "tickers", "liquidations", "klines"],
      depth: 200,
      started_at: "2026-09-01T00:00:00Z",
      retention_days: null,
      disk_bytes: 812340221100,
      rows_last_hour: 41220118,
      lag_ms: 42,
      added_by: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001",
    },
    {
      id: "e1000000-0000-4000-8000-000000000002",
      symbol: "ETHUSDT",
      reason: "chart_open",
      pinned: false,
      state: "recording",
      lingering: true,
      linger_until: "2026-09-14T11:00:30Z",
      streams: ["trades", "orderbook_delta", "tickers"],
      depth: 50,
      started_at: "2026-09-14T09:58:00Z",
      retention_days: 30,
      disk_bytes: 1220004410,
      rows_last_hour: 8122004,
      lag_ms: 31,
      added_by: null,
    },
  ],
  meta: { next_cursor: null, has_more: false, count: 2 },
} satisfies RecordedSymbolPage;

/** `getRecordingStatus` example `healthy` (its endpoint is the example's text; nothing dials it). */
export const statusHealthy = {
  overall: "healthy",
  connections: [
    {
      endpoint: "wss://stream.bybit.com/v5/public/linear",
      state: "connected",
      subscribed_topics: 14,
      connected_since: "2026-09-14T06:00:02Z",
      reconnects_last_hour: 0,
      last_ping_ms: 18,
    },
  ],
  symbols: [
    {
      symbol: "BTCUSDT",
      state: "recording",
      lag_ms: 42,
      rows_last_hour: 41220118,
      dropped_messages: 0,
      resyncs_last_hour: 1,
      last_event_at: "2026-09-14T10:31:02.104Z",
    },
    {
      symbol: "ETHUSDT",
      state: "recording",
      lingering: true,
      linger_until: "2026-09-14T11:00:30Z",
      lag_ms: 31,
      rows_last_hour: 8122004,
      dropped_messages: 0,
      resyncs_last_hour: 0,
      last_event_at: "2026-09-14T10:31:02.098Z",
    },
    { symbol: "SOLUSDT", state: "idle", refusal: "symbol_cap" },
  ],
  ingest_rate_msgs_per_sec: 18422,
  write_backlog_rows: 0,
  generated_at: "2026-09-14T10:31:02.900Z",
  policy: {
    autostart_delay_s: 60,
    autostop_grace_s: 1800,
    max_symbols: 2,
    warn_pct: 80,
    autostop_pct: 90,
    halt_pct: 95,
    autorecord_enabled: true,
  },
} satisfies RecordingStatus;

/** `getStorageUsage` example `usage`. */
export const storageUsage = {
  disk_total_bytes: 4000000000000,
  disk_used_bytes: 1204000000000,
  disk_free_bytes: 2796000000000,
  projected_full_at: "2028-03-27T10:31:03Z",
  daily_growth_bytes: 1450000000,
  cap_bytes: 2000000000000,
  level: 0,
  write_gate: "open",
  write_gate_reason: null,
  accelerate_retention: false,
  tiers: [
    { tier: "questdb", used_bytes: 640000000000, retention_days: 7 },
    { tier: "parquet", used_bytes: 548000000000, retention_days: 30 },
    { tier: "postgres", used_bytes: 16000000000, retention_days: null },
  ],
  symbols: [
    { symbol: "BTCUSDT", used_bytes: 812340221100, daily_growth_bytes: 780000000, pinned: true },
    { symbol: "ETHUSDT", used_bytes: 1220004410, daily_growth_bytes: 520000000, pinned: false },
  ],
  generated_at: "2026-09-14T10:31:03.000Z",
} satisfies StorageUsage;

/** `addRecordedSymbol`'s request example `manual`. */
export const addManual = {
  symbol: "SOLUSDT",
  streams: ["trades", "orderbook_delta", "tickers", "liquidations"],
  depth: 200,
  pinned: false,
  retention_days: 30,
} satisfies AddRecordedSymbolBody;

/** `purgeRecordedData`'s `409` examples `jobRunning` and `anchoredBound`. */
export const purgeJobRunning = {
  type: "https://candleviewer.local/errors/job_running",
  title: "A job of this kind is already queued or running; one runs at a time",
  status: 409,
  code: "job_running",
  detail: "A purge job is already running.",
} satisfies Problem;
export const purgeAnchoredBound = {
  type: "https://candleviewer.local/errors/idempotency_key_reuse",
  title: "Idempotency-Key reused with a different request payload",
  status: 409,
  code: "idempotency_key_reuse",
  detail: "This Idempotency-Key is anchored to another purge window bound.",
  errors: [
    {
      field: "before",
      rule: "idempotency_bound_mismatch",
      message: "anchored before is 2026-10-20T12:00:00Z",
    },
  ],
} satisfies Problem;

/** A problem body: `detail` and each `message` are server text the client must never render. */
export const problem = (status: number, code: string, extra: Partial<Problem> = {}): Problem => ({
  type: `https://candleviewer.local/errors/${code}`,
  title: "Refused",
  status,
  code,
  detail: "server detail, never rendered",
  ...extra,
});

/** `22`'s `stepUpRequired` challenge (its id and expiry), for the `recorder` class. */
export const stepUpRequired = problem(403, "step_up_required", {
  action_class: "recorder",
  challenge_id: "6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b",
  challenge_expires_at: "2026-09-14T10:36:02Z",
  action_summary: "Keep BTCUSDT data forever",
  target: null,
});

/**
 * A `recorder` frame (23 §15.8) carrying `statusHealthy` and `storageUsage` in the topic's
 * spellings: epoch-ms times, `used_bytes` the questdb plus parquet bytes, rows with their reason.
 */
export const frameHealthy = {
  overall: "healthy",
  policy: statusHealthy.policy,
  connections: [
    { state: "connected", subscribed_topics: 14, reconnects_last_hour: 0, last_ping_ms: 18 },
  ],
  symbols: [
    {
      symbol: "BTCUSDT",
      state: "recording",
      reason: "manual",
      pinned: true,
      lag_ms: 42,
      rows_last_hour: 41220118,
      dropped_messages: 0,
      resyncs_last_hour: 1,
      disk_bytes: 812340221100,
      last_event_at_ms: Date.parse("2026-09-14T10:31:02.104Z"),
    },
    {
      symbol: "ETHUSDT",
      state: "recording",
      reason: "chart_open",
      pinned: false,
      lingering: true,
      linger_until_ms: Date.parse("2026-09-14T11:00:30Z"),
      disk_bytes: 1220004410,
    },
    { symbol: "SOLUSDT", state: "idle", refusal: "symbol_cap" },
  ],
  ingest_rate_msgs_per_sec: 18422,
  write_backlog_rows: 0,
  storage: {
    disk_free_bytes: 2796000000000,
    daily_growth_bytes: 1450000000,
    cap_bytes: 2000000000000,
    used_bytes: 1188000000000,
    level: 0,
    write_gate: "open",
    write_gate_reason: null,
    accelerate_retention: false,
    projected_full_at_ms: Date.parse("2028-03-27T10:31:03Z"),
  },
} satisfies RecorderFrame;
