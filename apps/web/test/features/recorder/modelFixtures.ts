// E16-S01 slice 3: the `22` examples (listRecordedSymbols `two`, getRecordingStatus `healthy`,
// getStorageUsage `usage`) and E16-D02 §1's sample set, typed by the generated protocol types.
import type {
  RecordedSymbol,
  RecorderFrame,
  RecorderPolicy,
  RecordingStatus,
  StorageUsage,
} from "../../../src/features/recorder/model";

/** The examples' second, 2026-09-14 10:31:02 UTC. */
export const T0 = Date.parse("2026-09-14T10:31:02Z");

/** D02's defaults (decision 1): 60 s dwell, 30 min linger, 20 symbols, 80 / 90 / 95 %. */
export const POLICY = {
  autostart_delay_s: 60,
  autostop_grace_s: 1800,
  max_symbols: 20,
  warn_pct: 80,
  autostop_pct: 90,
  halt_pct: 95,
  autorecord_enabled: true,
} satisfies RecorderPolicy;

/** `22` listRecordedSymbols, example `two` (the fields the model reads). */
export const LIST_TWO = [
  {
    id: "e1000000-0000-4000-8000-000000000001",
    symbol: "BTCUSDT",
    reason: "manual",
    pinned: true,
    state: "recording",
    depth: 200,
    started_at: "2026-09-01T00:00:00Z",
    retention_days: null,
    disk_bytes: 812340221100,
  },
  {
    id: "e1000000-0000-4000-8000-000000000002",
    symbol: "ETHUSDT",
    reason: "chart_open",
    pinned: false,
    state: "recording",
    lingering: true,
    linger_until: "2026-09-14T11:00:30Z",
    depth: 50,
    started_at: "2026-09-14T09:58:00Z",
    retention_days: 30,
    disk_bytes: 1220004410,
  },
] satisfies RecordedSymbol[];

/** `22` getRecordingStatus, example `healthy` (its policy caps at 2 symbols). */
export const STATUS_HEALTHY = {
  overall: "healthy",
  symbols: [
    {
      symbol: "BTCUSDT",
      state: "recording",
      dropped_messages: 0,
      last_event_at: "2026-09-14T10:31:02.104Z",
    },
    {
      symbol: "ETHUSDT",
      state: "recording",
      lingering: true,
      linger_until: "2026-09-14T11:00:30Z",
      dropped_messages: 0,
      last_event_at: "2026-09-14T10:31:02.098Z",
    },
    { symbol: "SOLUSDT", state: "idle", refusal: "symbol_cap" },
  ],
  generated_at: "2026-09-14T10:31:02.900Z",
  policy: { ...POLICY, max_symbols: 2 },
} satisfies RecordingStatus;

/** `22` getStorageUsage, example `usage`. */
export const STORAGE_USAGE = {
  disk_total_bytes: 4_000_000_000_000,
  disk_used_bytes: 1_204_000_000_000,
  disk_free_bytes: 2_796_000_000_000,
  projected_full_at: "2028-03-27T10:31:03Z",
  daily_growth_bytes: 1_450_000_000,
  cap_bytes: 2_000_000_000_000,
  level: 0,
  write_gate: "open",
  write_gate_reason: null,
  accelerate_retention: false,
  tiers: [
    { tier: "questdb", used_bytes: 640_000_000_000, retention_days: 7 },
    { tier: "parquet", used_bytes: 548_000_000_000, retention_days: 30 },
    { tier: "postgres", used_bytes: 16_000_000_000, retention_days: null },
  ],
} satisfies StorageUsage;

type FrameRow = RecorderFrame["symbols"][number];

/** A `recorder` frame (23 §15.8) at T0 with D02's policy. */
export function modelFrame(
  symbols: FrameRow[],
  storage: NonNullable<RecorderFrame["storage"]> = {},
): RecorderFrame {
  return { overall: "healthy", policy: POLICY, symbols, storage };
}

const live = (symbol: string, extra: Partial<FrameRow> = {}): FrameRow => ({
  symbol,
  state: "recording",
  reason: "manual",
  last_event_at_ms: T0 - 1_000,
  ...extra,
});

/** D02 §1's sample set, board 01 `running`: BTC pinned, SOL held by a chart, XRP by a position. */
export const D02_FRAME: RecorderFrame = modelFrame([
  live("BTCUSDT", { pinned: true, disk_bytes: 34_800_000_000 }),
  live("ETHUSDT", { disk_bytes: 15_600_000_000 }),
  live("SOLUSDT", { reason: "chart_open", refusal: "chart_open", disk_bytes: 1_300_000 }),
  live("XRPUSDT", { reason: "position_open", refusal: "position_open", disk_bytes: 6_900_000 }),
  live("ADAUSDT", { state: "stopped", disk_bytes: 11_000_000_000 }),
]);
