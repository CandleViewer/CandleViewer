/**
 * E16-S01 (BQ-5): the recorder client's fixtures, taken from `docs/plan/22-api-openapi.yaml`'s
 * examples. Each `satisfies` its generated type, so a contract drift fails `typecheck`, and
 * `test/contract/recorderApi.contract.test.ts` reads the same examples out of `22` and compares.
 */
import type { generated } from "@candleviewer/protocol";
import type {
  AddRecordedSymbolBody,
  ArchiveImportResult,
  CompactionRunResult,
  HealthReport,
  ImportBody,
  JobAccepted,
  RecordedSymbolPage,
  RecordingStatus,
  RetentionPoliciesSaved,
  RetentionPolicyList,
  RetentionPurgeResult,
  RetentionSweepResult,
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

// E16-S03 / E16-S04: the retention, import and health calls. Where `22` has an example the fixture
// is it (`test/contract/recorder{Retention,Storage}.contract.test.ts` compares); the import's `202`
// and the job results have none, so those are the shapes the routes serve, as the backend's
// `tests/contract/test_recording_retention_contract.py` pins them, each held to its schema's keys.

/** `listRetentionPolicies` example `defaults`: two global rows and ETHUSDT's override. */
export const retentionDefaults = {
  items: [
    {
      id: "f1000000-0000-4000-8000-000000000001",
      stream: "trades",
      retain_days: 30,
      action: "archive_parquet",
      symbol: null,
      applies_to_pinned: false,
    },
    {
      id: "f1000000-0000-4000-8000-000000000002",
      stream: "orderbook_delta",
      retain_days: 7,
      action: "archive_parquet",
      symbol: null,
      applies_to_pinned: false,
    },
    {
      id: "f1000000-0000-4000-8000-000000000003",
      stream: "orderbook_delta",
      retain_days: 3,
      action: "drop",
      symbol: "ETHUSDT",
      applies_to_pinned: false,
    },
  ],
} satisfies RetentionPolicyList;

/** The one stored row both `setRetentionPolicies` `200` examples answer. */
const tradesSaved = {
  id: "f2000000-0000-4000-8000-000000000001",
  stream: "trades",
  retain_days: 30,
  action: "archive_parquet",
  symbol: null,
  applies_to_pinned: false,
  updated_at: "2026-09-14T10:31:03Z",
} satisfies RetentionPoliciesSaved["items"][number];

/** `setRetentionPolicies` example `scheduled`: saved for the next nightly run, no sweep started. */
export const retentionScheduled = {
  items: [tradesSaved],
  job_id: null,
} satisfies RetentionPoliciesSaved;

/** `setRetentionPolicies` example `appliedNow`: `apply_now=true` started the sweep `job_id`. */
export const retentionAppliedNow = {
  items: [tradesSaved],
  job_id: "19000000-0000-4000-8000-000000000002",
} satisfies RetentionPoliciesSaved;

/** `getHealth` example `degraded` (SCR-142's tiers: `postgres`, `questdb`, `parquet_store`). */
export const healthDegraded = {
  overall: "degraded",
  version: "1.0.0",
  git_sha: "a91f0c3",
  uptime_seconds: 184220,
  server_time: "2026-09-14T10:37:10Z",
  clock_offset_ms: 4,
  components: [
    { name: "postgres", state: "healthy", latency_ms: 2, detail: "pool 4/20" },
    { name: "questdb", state: "healthy", latency_ms: 6, detail: "ingest 18.4k msg/s" },
    {
      name: "parquet_store",
      state: "healthy",
      latency_ms: 44,
      detail: "last sync 2026-09-14T10:00:00Z",
    },
    {
      name: "bybit_public_ws",
      state: "healthy",
      latency_ms: 18,
      detail: "14 topics, 0 reconnects/h",
    },
    {
      name: "bybit_private_ws",
      state: "degraded",
      latency_ms: 210,
      detail: "account a1000000… reconnected 3× in the last hour",
    },
    { name: "bybit_rest", state: "healthy", latency_ms: 118, detail: "rate budget 62% free" },
    { name: "oms", state: "healthy", latency_ms: 1, detail: "0 unreconciled orders" },
    { name: "rule_engine", state: "healthy", latency_ms: 1, detail: "4 armed, 0 errors/h" },
    { name: "recorder", state: "healthy", latency_ms: 42, detail: "2 symbols recording" },
    {
      name: "disk",
      state: "warning",
      latency_ms: 0,
      detail: "30% free; projected full 2027-02-11",
    },
  ],
  alerts_active: 1,
} satisfies HealthReport;

/** `importTradeArchive`'s body: E16-D04's fixture range, BTCUSDT over January 2026. */
export const importJanuary = {
  symbol: "BTCUSDT",
  from: "2026-01-01",
  to: "2026-01-31",
} satisfies ImportBody;

/** `importTradeArchive`'s `202`, which `22` gives no example: the job to poll. */
export const importAccepted = {
  job_id: "19000000-0000-4000-8000-000000000003",
} satisfies JobAccepted;

/** An `apply_now` sweep's `Job.result`: one partition deleted, one kept late, one failed. */
export const sweepResult = {
  deleted: 1,
  freed_bytes: 2048,
  skipped: 1,
  failed: 1,
  skipped_locked: false,
} satisfies RetentionSweepResult;

/** A compaction's `Job.result`; its job reports `kind: retention_sweep`, as a sweep's does. */
export const compactionResult = {
  compacted: 3,
  skipped: 1,
  deferred: ["trades/symbol=BTCUSDT/dt=2026-10-16"],
  failed: ["trades/symbol=ETHUSDT/dt=2026-10-15"],
} satisfies CompactionRunResult;

/** A purge's `Job.result`: two days deleted, two kept because another symbol shares them. */
export const purgeResult = {
  deleted: 2,
  freed_bytes: 1220004410,
  skipped: [{ partition: "2026-09-03", reason: "shared_partition" }],
  protected: [{ partition: "2026-09-04", reason: "shared_partition" }],
  failed: 0,
} satisfies RetentionPurgeResult;

/** An import's `Job.result`: 27 files written, 1 from an earlier run, 2 skipped, 1 overlap. */
export const importResult = {
  symbol: "BTCUSDT",
  from: "2026-06-01",
  to: "2026-06-30",
  files_total: 30,
  files_processed: 27,
  files_already_imported: 1,
  files_skipped: [
    { file: "BTCUSDT2026-06-07.csv.gz", reason: "import_checksum_failed" },
    { file: "BTCUSDT2026-06-09.csv.gz", reason: "import_parse_failed" },
  ],
  rows_written: 648,
  rows_discarded_overlap: 264,
  rows_discarded_duplicate: 2,
  overlap: [{ from: "2026-06-20T00:00:00Z", to: "2026-07-01T00:00:00Z" }],
  bytes_downloaded: 1048576,
  already_imported: { rows_written: 24, rows_discarded_overlap: 0, rows_discarded_duplicate: 0 },
  streams: ["trades"],
  source: "archive",
} satisfies ArchiveImportResult;
