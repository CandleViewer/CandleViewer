/**
 * SCR-142's model (E16-S04; E16-D04 §2–§5, §14; E16-D06 §16.2; BQ-5): the storage report, the live `storage` object
 * and the tier health as words. Pure: the generated protocol types in, plain values out. The level is read, never
 * derived from the bytes (`22` `getStorageUsage`); every figure carries its unit; what the contract does not serve
 * reads the design's "Meanwhile" fallback (E16-D06 §16.3: "all tiers", the compaction schedule, the release words),
 * never a PROPOSED field. Nothing here decides a write (C-12.4).
 */
import type { generated } from "@candleviewer/protocol";
import type { IconName } from "@candleviewer/ui";
import { DECK, fill } from "../copy";
import {
  GB,
  diskCard,
  fixed,
  formatBytes,
  formatClock,
  formatDate,
  formatDuration,
  formatGrowth,
  parseMs,
  type DiskFacts,
  type DiskLevel,
  type RecorderPolicy,
  type StorageUsage,
} from "../model";
import type { HealthReport } from "../recorderApi";
import { PANEL_TEXT } from "./panelCopy";
import { STORAGE_DECK } from "./storageCopy";

type ComponentState = generated.rest.components["schemas"]["ComponentState"];

/** The report's cadence, `CV_DISK_SAMPLE_INTERVAL_S` (`20` :908). */
export const SAMPLE_EVERY_MS = 60_000;
/** Stale after two samples without a new report (D04 §2 (a), `SCR-142/stale-sample`). */
export const STALE_AFTER_MS = 2 * SAMPLE_EVERY_MS;
/** The lag warning: five ILP batches of 5,000 rows behind (D04-Q4, PROPOSED with D04-G4; D04-D8). */
const LAG_BATCHES = 5;
const LAG_BATCH_ROWS = 5_000;
export const LAG_WARN_ROWS = LAG_BATCHES * LAG_BATCH_ROWS;

const TB = 1e12;
const MB = 1e6;
const DAY_MS = 86_400_000;

/** "1.2 TB" from 1 TB up, else the page's GB / MB ("900.0 GB"): the volume's figures (D04 §2 (b)). */
export const formatVolume = (bytes: number): string =>
  bytes >= TB ? `${fixed(bytes / TB, 1)} TB` : formatBytes(bytes);
/**
 * A symbol's growth: "780 MB/day" while it rounds under 1,000 MB, else "1.45 GB/day" (D04 §4 `TIER/per-symbol`):
 * the unit follows the rounded figure, so 999.5 MB never reads "1,000 MB/day" (C-486P3-14, as A-5309-10's sizes).
 */
export const formatRate = (bytesPerDay: number): string =>
  Math.round(bytesPerDay / MB) >= GB / MB
    ? dayRate(bytesPerDay)
    : `${fixed(bytesPerDay / MB, 0)} MB/day`;
/** The disk-level growth, "1.45 GB/day" (`storage.projection`'s `{growth}`). */
const dayRate = (bytesPerDay: number): string => `${formatGrowth(bytesPerDay)}/day`;
/** "18,400", "660,000": D04's grouping of a count. */
export const formatCount = (n: number): string => fixed(n, 0);
const percent = (part: number, whole: number): string => `${fixed((part / whole) * 100, 1)} %`;
const round1 = (value: number): number => Math.round(value * 10) / 10;

/** A sample's age in its largest whole unit: "45 s", "3 min", "1 h 5 min". */
export function ageText(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const rest = minutes % 60;
  return `${Math.floor(minutes / 60)} h${rest === 0 ? "" : ` ${rest} min`}`;
}

export interface StampView {
  readonly text: string;
  readonly stale: boolean;
}

const [STAMP] = STORAGE_DECK["storage.stamp"];
const [STAMP_STALE] = STORAGE_DECK["storage.stamp.stale"];
const [SAMPLING] = STORAGE_DECK["storage.stamp.sampling"];

/**
 * The sample stamp (D04 §2 (a); `14` §0.5 rule 4: the last-good time always shown): "Sampling…" before any report;
 * its stale form once the report is older than two samples, or when the latest read failed (`SCR-142/unavailable`,
 * never the fresh form); nothing after a failure with no report to name.
 */
export function stampView(
  generatedAtMs: number | null,
  nowMs: number,
  failed: boolean,
): StampView | null {
  if (generatedAtMs === null) return failed ? null : { text: SAMPLING, stale: false };
  const age = Math.max(0, nowMs - generatedAtMs);
  const clock = formatClock(generatedAtMs);
  if (failed || age > STALE_AFTER_MS) {
    return { text: fill(STAMP_STALE, { "{HH:MM:SS}": clock, "{age}": ageText(age) }), stale: true };
  }
  const every = formatDuration(SAMPLE_EVERY_MS / 1000);
  return { text: fill(STAMP, { "{HH:MM:SS}": clock, "{every}": every }), stale: false };
}

/** A CMP-023 `meter`: its label names what it divides (D04-D1, D04-A2); the value text carries the units. */
export interface MeterView {
  readonly label: string;
  readonly value: number;
  readonly text: string;
  readonly tone: "default" | "warning" | "danger";
}

/** "Recording budget: {used} of {cap} ({pct})" is the bar's label, then its value text (CMP-023's head). */
function labelled(template: string): readonly [string, string] {
  const at = template.indexOf(": ");
  return [template.slice(0, at), template.slice(at + 2)];
}
const [BUDGET, BUDGET_TEXT] = labelled(STORAGE_DECK["storage.meter.budget"][0]);
const [VOLUME, VOLUME_TEXT] = labelled(STORAGE_DECK["storage.meter.volume"][0]);
/** The budget's fill by `level` (D04 §2 (b), §11): primary, warning at 1–2, danger at 3. */
const LEVEL_TONE: Readonly<Record<DiskLevel, MeterView["tone"]>> = {
  0: "default",
  1: "warning",
  2: "warning",
  3: "danger",
};

/** The recording budget: the QuestDB plus Parquet bytes over `cap_bytes`, live from the frame (`22` :5424). */
export function budgetMeter(f: DiskFacts): MeterView | null {
  const { usedBytes: used, capBytes: cap } = f;
  if (used === null || cap === null || cap <= 0) return null;
  return {
    label: BUDGET,
    value: round1((used / cap) * 100),
    text: fill(BUDGET_TEXT, {
      "{used}": formatBytes(used),
      "{cap}": formatBytes(cap),
      "{pct}": percent(used, cap),
    }),
    tone: LEVEL_TONE[f.level],
  };
}

/** The disk volume: `disk_used_bytes` over `disk_total_bytes`, with the free space, from the sample. */
export function volumeMeter(report: StorageUsage | null): MeterView | null {
  const total = report?.disk_total_bytes;
  const used = report?.disk_used_bytes;
  if (total === undefined || used === undefined || total <= 0) return null;
  const free = report?.disk_free_bytes ?? Math.max(0, total - used);
  return {
    label: VOLUME,
    value: round1((used / total) * 100),
    text: fill(VOLUME_TEXT, {
      "{used}": formatVolume(used),
      "{total}": formatVolume(total),
      "{pct}": percent(used, total),
      "{free}": formatVolume(free),
    }),
    tone: "default",
  };
}

/**
 * E16-D02 §8.3's headline keyed on `level` (`storage.headline.*`), as SCR-140's disk card words it, with the page's
 * history (its rows' oldest `started_at`): growth 0 reads "Too early to project" under an hour of it, then "Steady"
 * (A-5309-03), so the section and the card above it never disagree (C-486P3-02).
 */
export const headlineOf = (
  f: DiskFacts,
  policy: RecorderPolicy | null,
  nothingRecorded: boolean,
  nowMs: number,
  historySinceMs: number | null,
): string => diskCard(f, policy, nothingRecorded, nowMs, historySinceMs).headline;

/** Days to `pct` % of the budget at the current growth, nearest day; null with no runway to state. */
function daysTo(pct: number, f: DiskFacts): number | null {
  const { usedBytes: used, capBytes: cap, growthBytesPerDay: growth } = f;
  if (used === null || cap === null || growth === null || growth <= 0) return null;
  const days = Math.round(((pct / 100) * cap - used) / growth);
  return days < 0 ? null : days;
}

const [PROJECTION] = STORAGE_DECK["storage.projection"];

/**
 * "Full in about {d} days ({date}) at {growth}: the {wall} is the nearer wall": `projected_full_at` is to the nearer
 * wall (`24` :3830), named by comparing the budget's room with the volume's free space, and the other wall's runway
 * after it in the deck example's words ("(the volume about 1,928 days)"). None without a date or growth.
 */
export function projectionLine(f: DiskFacts, nowMs: number): string | null {
  const { projectedFullAtMs: at, growthBytesPerDay: growth, usedBytes: used, capBytes: cap } = f;
  if (at === null || growth === null || growth <= 0 || at <= nowMs) return null;
  const budgetDays = used === null || cap === null ? null : (cap - used) / growth;
  const volumeDays = f.freeBytes === null ? null : f.freeBytes / growth;
  const volumeNearer = budgetDays !== null && volumeDays !== null && volumeDays < budgetDays;
  const line = fill(PROJECTION, {
    "{d}": formatCount(Math.round((at - nowMs) / DAY_MS)),
    "{date}": formatDate(at),
    "{growth}": dayRate(growth),
    "{wall}": volumeNearer ? "volume" : "budget",
  });
  const other = volumeNearer ? budgetDays : volumeDays;
  if (other === null) return line;
  const otherWall = volumeNearer ? "budget" : "volume";
  return `${line} (the ${otherWall} about ${formatCount(Math.round(other))} days)`;
}

const [FORMULA] = STORAGE_DECK["storage.formula"];

/** E16-D02's formula for the autostop runway (`storage.formula`), below the pause only (levels 0 and 1). */
export function formulaLine(f: DiskFacts, policy: RecorderPolicy | null): string | null {
  const { usedBytes: used, capBytes: cap, growthBytesPerDay: growth } = f;
  if (policy === null || f.level > 1 || used === null || cap === null) return null;
  const days = daysTo(policy.autostop_pct, f);
  if (days === null || growth === null) return null;
  return fill(FORMULA, {
    "{autostop}": policy.autostop_pct,
    "{cap}": formatBytes(cap),
    "{used}": formatBytes(used),
    "{growth}": dayRate(growth),
    "{d}": formatCount(days),
  });
}

const [SCALE] = DECK["d02.8.r19"];

/** The threshold scale (`storage.scale`), from the server's ladder (`20` :905–907). */
export function scaleLine(policy: RecorderPolicy | null): string | null {
  if (policy === null) return null;
  return fill(SCALE, {
    "{warn}": policy.warn_pct,
    "{autostop}": policy.autostop_pct,
    "{halt}": policy.halt_pct,
  });
}

export interface DegradationView {
  readonly title: string;
  readonly lines: readonly string[];
}

const [FIRST_STOPS] = STORAGE_DECK["storage.degradation"];
const [DETAIL] = STORAGE_DECK["storage.degradation.detail"];
const [HALT_NEXT] = STORAGE_DECK["storage.autostop.next"];
const [LEVEL_3_FACT] = STORAGE_DECK["storage.level3.fact"];

/**
 * What stops first, on every level ≥ 1 (AC 2; D04 §1.4, D04-D7): "Recording pauses before trading is affected." and
 * the detail line with the server's thresholds; at level 2 when recording stops; at level 3 that open positions keep
 * recording. Nothing at level 0.
 */
export function degradationOf(f: DiskFacts, policy: RecorderPolicy | null): DegradationView | null {
  if (f.level === 0) return null;
  const detail =
    policy === null
      ? DETAIL
      : DETAIL.replace(
          /\b(90|95) %/g,
          (_, n: string) => `${n === "90" ? policy.autostop_pct : policy.halt_pct} %`,
        );
  const lines = [detail];
  const halt = f.level === 2 && policy !== null ? daysTo(policy.halt_pct, f) : null;
  if (halt !== null && policy !== null) {
    lines.push(fill(HALT_NEXT, { "{halt}": policy.halt_pct, "{d}": formatCount(halt) }));
  }
  if (f.level === 3) lines.push(LEVEL_3_FACT);
  return { title: FIRST_STOPS, lines };
}

/** A refused volume's cause, beside the headline (`SCR-142/volume-refused`). */
export const causeLine = (f: DiskFacts): string | null =>
  f.volumeRefused ? STORAGE_DECK["storage.volume_refused"][0] : null;

/** "Retention accelerated", a status word beside the headline while `accelerate_retention` holds. */
export const accelerationWord = (f: DiskFacts): string | null =>
  f.accelerateRetention ? STORAGE_DECK["storage.accelerated"][0] : null;

export type TierId = "questdb" | "parquet" | "postgres";
export const TIERS: readonly TierId[] = ["questdb", "parquet", "postgres"];

/** `HealthReport.components[].name` per tier: the `22` example's names, not an enum (D04-CG1). */
const COMPONENT: Readonly<Record<TierId, string>> = {
  questdb: "questdb",
  parquet: "parquet_store",
  postgres: "postgres",
};
const TITLE: Readonly<Record<TierId, string>> = {
  questdb: STORAGE_DECK["storage.tier.questdb"][0],
  parquet: STORAGE_DECK["storage.tier.parquet"][0],
  postgres: STORAGE_DECK["storage.tier.postgres"][0],
};
const [
  SIZE,
  SHARE,
  RETENTION,
  GROWTH,
  PROJECTED,
  HEALTH,
  INGESTION,
  LAST_COMPACTION,
  LAST_VACUUM,
  MIGRATION,
] = STORAGE_DECK["storage.tier.rows"];
const [HEALTHY, DEGRADED, WARNING, DOWN, NOT_DEPLOYED, NOT_REPORTED] =
  STORAGE_DECK["storage.tier.health"];
/** A `ComponentState` as its word and glyph (✓ healthy · ⚠ degraded / warning · ✗ down · plain not deployed). */
const STATE: Readonly<Record<ComponentState, readonly [string, IconName | null]>> = {
  healthy: [HEALTHY, "success"],
  degraded: [DEGRADED, "warning"],
  warning: [WARNING, "warning"],
  down: [DOWN, "error"],
  not_deployed: [NOT_DEPLOYED, null],
};
const [ALL_TIERS] = STORAGE_DECK["storage.tier.all_tiers"];
const [NOT_COUNTED] = STORAGE_DECK["storage.tier.not_counted"];
const [UNREACHABLE] = STORAGE_DECK["storage.tier.unreachable"];
const [SCHEDULE] = STORAGE_DECK["storage.compaction.schedule"];
const [INGESTION_LINE] = STORAGE_DECK["storage.ingestion"];

/** One card row: a value, else "—" with the shipped fallback beside it when the design names one. */
export interface TierRow {
  readonly label: string;
  readonly value: string | null;
  readonly fallback?: string;
  /** The Health row's glyph (the word carries the state; the glyph is never alone). */
  readonly icon?: IconName;
  /** The value is not current (its read failed, or its topic is stale): it keeps its text with a "stale" tag. */
  readonly stale?: true;
}

export interface TierHealth {
  readonly word: string;
  readonly icon: IconName | null;
  readonly down: boolean;
  readonly sinceMs: number | null;
}

export interface TierView {
  readonly tier: TierId;
  /** The card's heading ("QuestDB · hot"). */
  readonly title: string;
  /** The tier's name alone ("QuestDB"): `{Tier}` in the unreachable line. */
  readonly name: string;
  /** Size · Share of budget · Retention · Growth/day · Projected full · Health, then the tier's own rows. */
  readonly rows: readonly TierRow[];
  readonly health: TierHealth;
  /** "QuestDB unreachable since 10:24:03 UTC" while the tier is down. */
  readonly unreachable: string | null;
}

/** The two ingestion-pressure numbers, from the frame (or the status before one; `23` :4060–4061). */
export interface Pressure {
  readonly rate: number | null;
  readonly backlog: number | null;
}

/** What the cards' rows know beyond the reads themselves. */
export interface TierFlags {
  /** The backlog warning holds (`SCR-142/lag-warning`): QuestDB's healthy reads "warning" (C-486P3-04). */
  readonly lagging?: boolean;
  /** The latest health read failed: the last health keeps its words, tagged stale (C-486P3-07). */
  readonly healthStale?: boolean;
  /** The pressure numbers come from a stale topic: the Ingestion row is tagged stale (C-486P3-08). */
  readonly pressureStale?: boolean;
}

/** A tier's health from `/admin/health`: "not reported" when the component is absent (D04-CG1). */
export function tierHealth(health: HealthReport | null, tier: TierId): TierHealth {
  const component = health?.components?.find((c) => c.name === COMPONENT[tier]);
  const state = component?.state;
  const [word, icon] =
    state !== undefined && Object.hasOwn(STATE, state) ? STATE[state] : [NOT_REPORTED, null];
  return { word, icon, down: state === "down", sinceMs: parseMs(component?.last_good_at) };
}

/** "Ingest 18,400 msg/s, backlog 25,000 rows, lag —": the lag is D04-G4's and reads "—". */
export const ingestionLine = (rate: number, backlog: number): string =>
  fill(INGESTION_LINE, { "{rate}": formatCount(rate), "{rows}": formatCount(backlog) });

const missing = (label: string, fallback: string | null = null): TierRow =>
  fallback === null ? { label, value: null } : { label, value: null, fallback };

function ownRows(
  tier: TierId,
  health: HealthReport | null,
  pressure: Pressure,
  flags: TierFlags,
): TierRow[] {
  if (tier === "questdb") {
    const { rate, backlog } = pressure;
    const value = rate === null || backlog === null ? null : ingestionLine(rate, backlog);
    return [
      {
        label: INGESTION,
        value,
        ...(value !== null && flags.pressureStale === true ? { stale: true } : {}),
      },
    ];
  }
  if (tier === "parquet") return [missing(LAST_COMPACTION, SCHEDULE)];
  // D04-G7's fallback: the release words, `HealthReport.version`.
  return [missing(LAST_VACUUM), { label: MIGRATION, value: health?.version ?? null }];
}

/** The Health row: the served word and glyph, or QuestDB's backlog "warning" over a served "healthy". */
function healthRow(tier: TierId, state: TierHealth, stale: boolean, flags: TierFlags): TierRow {
  const lagging = flags.lagging === true && tier === "questdb" && state.word === HEALTHY;
  const [value, icon] = lagging ? [WARNING, "warning" as const] : [state.word, state.icon];
  return {
    label: HEALTH,
    value,
    ...(icon === null ? {} : { icon }),
    ...(stale ? { stale: true } : {}),
  };
}

/**
 * The three tier cards (AC 1; D04 §4): size, share of the budget (Postgres is not counted in it, `22` :5424) and
 * retention from the report; growth and the projected date as "—" beside the disk-level figure labelled "all tiers"
 * (D04-G1); health as the `ComponentState` word, QuestDB's "warning" while the backlog warning holds (D04
 * `SCR-142/lag-warning`: the backlog never hides a worse served word); then each tier's own rows.
 */
export function tierViews(
  report: StorageUsage | null,
  health: HealthReport | null,
  f: DiskFacts,
  pressure: Pressure,
  flags: TierFlags = {},
): TierView[] {
  const cap = report?.cap_bytes ?? null;
  const growth = f.growthBytesPerDay;
  const until = f.projectedFullAtMs;
  return TIERS.map((tier) => {
    const listed = report?.tiers?.find((t) => t.tier === tier);
    const used = listed?.used_bytes ?? null;
    const retention = listed?.retention_days ?? null;
    const state = tierHealth(health, tier);
    const name = TITLE[tier].split(" · ")[0] ?? TITLE[tier];
    const share =
      tier === "postgres"
        ? NOT_COUNTED
        : used === null || cap === null || cap <= 0
          ? null
          : percent(used, cap);
    const rows: TierRow[] = [
      { label: SIZE, value: used === null ? null : formatBytes(used) },
      { label: SHARE, value: share },
      { label: RETENTION, value: retention === null ? null : `${retention} d` },
      missing(GROWTH, growth === null ? null : fill(ALL_TIERS, { "{growth}": dayRate(growth) })),
      missing(
        PROJECTED,
        until === null ? null : fill(ALL_TIERS, { "{growth}": formatDate(until) }),
      ),
      // A failed health read leaves the last served word, tagged; "not reported" is no figure to tag.
      healthRow(tier, state, flags.healthStale === true && state.word !== NOT_REPORTED, flags),
      ...ownRows(tier, health, pressure, flags),
    ];
    const unreachable = !state.down
      ? null
      : state.sinceMs === null
        ? fill(PANEL_TEXT.unreachable, { "{Tier}": name })
        : fill(UNREACHABLE, { "{Tier}": name, "{HH:MM:SS}": formatClock(state.sinceMs) });
    return { tier, title: TITLE[tier], name, rows, health: state, unreachable };
  });
}

export interface SymbolRow {
  readonly symbol: string;
  readonly size: string | null;
  readonly growth: string | null;
  readonly share: string | null;
  readonly pinned: boolean;
}

/** The hot tier's per-symbol table (D04 §4 `TIER/per-symbol`): the report's `symbols[]`, in its order. */
export function symbolRows(report: StorageUsage | null): SymbolRow[] {
  const cap = report?.cap_bytes;
  return (report?.symbols ?? []).flatMap((s) => {
    if (s.symbol === undefined) return [];
    const used = s.used_bytes;
    return [
      {
        symbol: s.symbol,
        size: used === undefined ? null : formatBytes(used),
        growth: s.daily_growth_bytes === undefined ? null : formatRate(s.daily_growth_bytes),
        share: used === undefined || cap === undefined || cap <= 0 ? null : percent(used, cap),
        pinned: s.pinned === true,
      },
    ];
  });
}

const [ATTRIBUTED] = STORAGE_DECK["storage.symbols.attributed"];

/** "{sum} of {used} attributed to symbols ({pct})" (D04-CG3): the symbols listed against the recorded bytes. */
export function attributionLine(report: StorageUsage | null): string | null {
  const symbols = report?.symbols ?? [];
  const recorded = (report?.tiers ?? [])
    .filter((t) => t.tier === "questdb" || t.tier === "parquet")
    .reduce((sum, t) => sum + (t.used_bytes ?? 0), 0);
  if (symbols.length === 0 || recorded <= 0) return null;
  const sum = symbols.reduce((total, s) => total + (s.used_bytes ?? 0), 0);
  return fill(ATTRIBUTED, {
    "{sum}": formatBytes(sum),
    "{used}": formatBytes(recorded),
    "{pct}": percent(sum, recorded),
  });
}

/** The backlog at or past the warning (D04-D8: keyed on the produced number, not a lag field). */
export const isBacklogged = (rows: number | null): boolean =>
  rows !== null && rows >= LAG_WARN_ROWS;

/** "Ingestion backlog 25,000 rows — writes are behind the feed" (`storage.lag.banner`). */
export const lagBannerOf = (rows: number): string =>
  fill(STORAGE_DECK["storage.lag.banner"][0], { "{rows}": formatCount(rows) });

/**
 * The warning's rule, stated beside its banner (D04 `SCR-142/lag-warning`: "the threshold stated beside the banner,
 * 5 batches"; C-486P3-04 (a)): "Threshold: 5 batches of 5,000 rows for two samples", PROPOSED with D04-G4 / D04-Q4.
 */
export const lagThresholdLine = (): string =>
  fill(PANEL_TEXT.lagThreshold, {
    "{batches}": LAG_BATCHES,
    "{rows}": formatCount(LAG_BATCH_ROWS),
  });
