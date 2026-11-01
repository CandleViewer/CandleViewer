/**
 * E16-S04, SCR-142's fixtures: E16-D04's fixture (the header's, derived from `22`'s `getStorageUsage` example
 * `usage`, sampled 2026-09-14 10:31:03 UTC) and its level states (80.5 %, 90.0 %, 95.0 % and the refused volume),
 * the `getHealth` example's three tiers (a QuestDB card down since 10:24:03 UTC), `recorder` frames in the topic's
 * spellings, and the jobs' answers. Each `satisfies` its generated type (C-4.16), so a contract drift fails
 * `typecheck`.
 */
import type {
  HealthReport,
  Job,
  StorageUsage,
} from "../../../../src/features/recorder/recorderApi";
import type { RecorderFrame, RecordingStatus } from "../../../../src/features/recorder/model";
import { healthDegraded, statusHealthy, storageUsage } from "../fixtures";

/** The report's sample time, 2026-09-14 10:31:03 UTC; the clock starts one second later. */
export const SAMPLED = Date.parse("2026-09-14T10:31:03Z");
export const CLOCK = SAMPLED + 1_000;

export const REPORT: StorageUsage = storageUsage;
export const STATUS: RecordingStatus = statusHealthy;
export const HEALTH: HealthReport = healthDegraded;
/** The ladder: warn 80, autostop 90, halt 95 % of `cap_bytes` (`20` :905–907). */
export const POLICY = statusHealthy.policy;

/** The report with its recorded bytes scaled to `budgetGb` (QuestDB 54 %, Parquet the rest) and `patch`. */
export function reportAt(budgetGb: number, patch: Partial<StorageUsage> = {}): StorageUsage {
  const questdb = Math.round(budgetGb * 0.54 * 1e9);
  return {
    ...REPORT,
    tiers: [
      { tier: "questdb", used_bytes: questdb, retention_days: 7 },
      { tier: "parquet", used_bytes: budgetGb * 1e9 - questdb, retention_days: 30 },
      { tier: "postgres", used_bytes: 16000000000, retention_days: null },
    ],
    ...patch,
  };
}

/** `SCR-142/low-disk-warning`: level 1 at 80.5 % (1,610.0 GB). */
export const LEVEL_1 = reportAt(1610, { level: 1 });
/** `SCR-142/autostop`: level 2 at 90.0 % (1,800.0 GB), retention accelerated. */
export const LEVEL_2 = reportAt(1800, { level: 2, accelerate_retention: true });
/** `SCR-142/read-only-disk-full`: level 3 at 95.0 %, the gate closed by the halt. */
export const LEVEL_3 = reportAt(1900, {
  level: 3,
  write_gate: "closed",
  write_gate_reason: "disk_halt",
  accelerate_retention: true,
});
/** `SCR-142/volume-refused`: level 3 with the bytes unchanged (59.4 %): the level is read, never derived. */
export const VOLUME_REFUSED: StorageUsage = {
  ...REPORT,
  level: 3,
  write_gate: "closed",
  write_gate_reason: "volume_refused",
};

/** `getHealth` with one tier's component replaced. */
export function healthWith(
  name: string,
  patch: NonNullable<HealthReport["components"]>[number],
): HealthReport {
  return {
    ...HEALTH,
    components: (HEALTH.components ?? []).map((c) => (c.name === name ? { ...c, ...patch } : c)),
  };
}

/** `SCR-142/tier-unreachable-questdb`: QuestDB down since 10:24:03 UTC, the other two healthy. */
export const QUESTDB_DOWN = healthWith("questdb", {
  name: "questdb",
  state: "down",
  last_good_at: "2026-09-14T10:24:03Z",
});

/** A `recorder` frame carrying `REPORT`'s figures live (23 §15.8) and the two pressure numbers. */
export function frameWith(
  patch: Partial<NonNullable<RecorderFrame["storage"]>> = {},
  pressure: { readonly rate?: number; readonly backlog?: number } = {},
): RecorderFrame {
  return {
    overall: "healthy",
    policy: POLICY,
    symbols: [
      { symbol: "BTCUSDT", state: "recording", reason: "manual", pinned: true },
      { symbol: "ETHUSDT", state: "recording", reason: "manual", pinned: false },
    ],
    ingest_rate_msgs_per_sec: pressure.rate ?? 18400,
    write_backlog_rows: pressure.backlog ?? 0,
    storage: {
      used_bytes: 1188000000000,
      cap_bytes: 2000000000000,
      level: 0,
      write_gate: "open",
      write_gate_reason: null,
      accelerate_retention: false,
      daily_growth_bytes: 1450000000,
      disk_free_bytes: 2796000000000,
      projected_full_at_ms: Date.parse("2028-03-27T10:31:03Z"),
      ...patch,
    },
  };
}

export const COMPACT_JOB = "19000000-0000-4000-8000-000000000011";
export const IMPORT_JOB = "19000000-0000-4000-8000-000000000012";

/** A `getJob` answer for `id`. */
export const jobAnswer = (id: string, patch: Partial<Job> = {}): Job => ({
  id,
  status: "running",
  progress_pct: 0,
  started_at: "2026-09-14T10:38:00Z",
  finished_at: null,
  result: null,
  error: null,
  ...patch,
});
