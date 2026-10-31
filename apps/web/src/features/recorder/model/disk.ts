/**
 * SCR-140's disk card, keyed on `level` (E16-D02 §3, §8.3). The ladder is latched with hysteresis
 * (24 §13.4.1), so the card reads `level` and never derives it from the bytes: a state-first
 * headline that names the way back, the bar's numeric text, the explanation, the projection
 * formula as text, the wall a bare `projected_full_at` refers to, and the threshold scale.
 */
import { DECK, TEXT, fill } from "../copy";
import { GB, fixed, formatBytes, formatCap, formatGrowth, parseMs } from "./format";
import type { RecorderFrame, RecorderPolicy, StorageUsage } from "./types";

export type DiskLevel = 0 | 1 | 2 | 3;

/** The card's figures: the frame's `storage` (1 Hz) over the first-paint `StorageUsage` (BQ-7). */
export interface DiskFacts {
  readonly level: DiskLevel;
  /** WS `used_bytes`; before a frame, REST's `questdb` + `parquet` tiers (22 `getStorageUsage`). */
  readonly usedBytes: number | null;
  readonly capBytes: number | null;
  readonly growthBytesPerDay: number | null;
  readonly projectedFullAtMs: number | null;
  readonly freeBytes: number | null;
  readonly gateClosed: boolean;
  readonly volumeRefused: boolean;
  readonly accelerateRetention: boolean;
}

export interface DiskCard {
  readonly level: DiskLevel;
  readonly tone: "primary" | "warning" | "danger";
  readonly headline: string;
  /** CMP-023's value and its numeric text (AC2: a number with units, never colour alone). */
  readonly meter: { readonly value: number; readonly max: number; readonly text: string } | null;
  readonly lines: readonly string[];
  readonly scale: string | null;
  /** §8.3's suggested actions (levels 1 and 2). */
  readonly suggested: readonly string[];
}

const [GROWING, USAGE, PROJECTION] = DECK["d02.8.r11"];
const [STEADY, STEADY_LINE] = DECK["d02.8.r12"];
const [TOO_EARLY, TOO_EARLY_LINE] = DECK["d02.8.r13"];
const [BUDGET_WALL, VOLUME_WALL] = DECK["d02.8.r14"];
const [NEAR, NEAR_LINE] = DECK["d02.8.r15"];
const [PAUSED, PAUSED_LINE, PAUSED_BY_VOLUME] = DECK["d02.8.r16"];
const [HALTED, HALTED_LINE] = DECK["d02.8.r17"];
const [NOTHING, NOTHING_LINE] = DECK["d02.8.r18"];
const [SCALE, ...SUGGESTED] = DECK["d02.8.r19"];
const DAY_MS = 86_400_000;
const HOUR_MS = 3_600_000;
const BUDGET_FULL = "the budget is full in about {d} days";

/** A field the frame carries wins, its `null` ("none now") included; else REST's. */
const pick = <T>(live: T | undefined, rest: T | undefined): T | undefined =>
  live !== undefined ? live : rest;

export function diskFacts(rest: StorageUsage | null, frame: RecorderFrame | null): DiskFacts {
  const live = frame?.storage;
  const tiers = (rest?.tiers ?? []).filter((t) => t.tier === "questdb" || t.tier === "parquet");
  const projected = pick(live?.projected_full_at_ms, parseMs(rest?.projected_full_at));
  return {
    level: live?.level ?? rest?.level ?? 0,
    usedBytes:
      live?.used_bytes ??
      (tiers.length === 0 ? null : tiers.reduce((sum, t) => sum + (t.used_bytes ?? 0), 0)),
    capBytes: live?.cap_bytes ?? rest?.cap_bytes ?? null,
    growthBytesPerDay: live?.daily_growth_bytes ?? rest?.daily_growth_bytes ?? null,
    projectedFullAtMs: projected ?? null,
    freeBytes: live?.disk_free_bytes ?? rest?.disk_free_bytes ?? null,
    gateClosed: (live?.write_gate ?? rest?.write_gate) === "closed",
    volumeRefused: pick(live?.write_gate_reason, rest?.write_gate_reason) === "volume_refused",
    accelerateRetention: live?.accelerate_retention ?? rest?.accelerate_retention ?? false,
  };
}

type Values = Readonly<Record<string, string | number>>;

/** The figures' tokens; `{pct}` with `digits` decimals ("31 %" at level 0, "80.5 %" above). */
function figures(f: DiskFacts, digits: number, used = f.usedBytes): Values {
  const cap = f.capBytes;
  const known = used !== null && cap !== null && cap > 0;
  return {
    "{used}": used === null ? "—" : formatBytes(used),
    "{cap}": cap === null ? "—" : formatCap(cap),
    "{pct}": known ? fixed((used / cap) * 100, digits) : "—",
  };
}

const thresholds = (p: RecorderPolicy): Values => ({
  "{warn}": p.warn_pct,
  "{autostop}": p.autostop_pct,
  "{halt}": p.halt_pct,
  "{warn − 5}": p.warn_pct - 5,
  "{autostop − 5}": p.autostop_pct - 5,
  "{halt − 5}": p.halt_pct - 5,
});

/** "about {d} days" to `pct` % of the budget: (pct % × cap − used) ÷ growth, nearest day (§1: 127.5 → 128). */
function daysTo(pct: number, f: DiskFacts): number | null {
  const { usedBytes: used, capBytes: cap, growthBytesPerDay: growth } = f;
  if (used === null || cap === null || growth === null || growth <= 0) return null;
  return Math.max(0, Math.round(((pct / 100) * cap - used) / growth));
}

/** Fills `{d}`, or drops its clause when there is no runway yet, so no "{d}" ever renders. */
const withDays = (template: string, clause: string, days: number | null): string =>
  days === null ? template.replace(clause, "") : fill(template, { "{d}": days });
/** The headline's state word alone, where its way back cannot be stated. */
const head = (headline: string): string => headline.split(" · ")[0] ?? headline;
/** Boards 04 and 05 set the line's first sentence ("Recording budget … used (…)") as the bar's text. */
function splitFirst(line: string): readonly [string, string] {
  const end = line.indexOf(". ");
  return [line.slice(0, end), line.slice(end + 2)];
}

/**
 * The budget's share is below `pct`'s release point (24 §13.4.1: a level releases 5 points lower), so the
 * level the ladder latched is held by the disk volume's free space, not the budget.
 */
function heldByVolume(f: DiskFacts, used: number | null, pct: number | undefined): boolean {
  const cap = f.capBytes;
  if (pct === undefined || used === null || cap === null || cap <= 0) return false;
  return (used / cap) * 100 < pct - 5;
}

/**
 * `historySinceMs`: the oldest row's `started_at`, the page's history (A-5309-03). The server folds "not
 * measured yet" into a growth of 0, so a growth of 0 under an hour of history is too early, never Steady.
 */
export function diskCard(
  f: DiskFacts,
  policy: RecorderPolicy | null,
  nothingRecorded: boolean,
  nowMs: number,
  historySinceMs: number | null = null,
): DiskCard {
  const { level, usedBytes: used, capBytes: cap, growthBytesPerDay: growth } = f;
  const nothing = level === 0 && nothingRecorded && (used ?? 0) === 0;
  const value = nothing ? 0 : used;
  const vars = { ...figures(f, level === 0 ? 0 : 1, value), ...(policy && thresholds(policy)) };
  /** Without the policy a headline keeps its state word only: its thresholds are unknown. */
  const way = (headline: string): string => (policy === null ? head(headline) : headline);
  const card = (headline: string, bar: string, lines: readonly string[] = []): DiskCard => ({
    level,
    tone: level === 0 ? "primary" : level === 3 ? "danger" : "warning",
    headline: fill(headline, vars),
    meter:
      value === null || cap === null || cap <= 0
        ? null
        : { value, max: cap, text: fill(bar, vars) },
    lines: lines.map((line) => fill(line, vars)),
    scale: policy === null ? null : fill(SCALE, vars),
    suggested: level === 1 || level === 2 ? SUGGESTED : [],
  });
  const accelerated = f.accelerateRetention ? [TEXT.accelerated] : [];
  if (level === 3) {
    return card(f.volumeRefused ? head(HALTED) : way(HALTED), TEXT.levelThreeMeter, [HALTED_LINE]);
  }
  if (level === 2) {
    const [bar, rest] = splitFirst(PAUSED_LINE);
    // Level 2 holds on the budget or the volume; below the budget's release point, the volume.
    const byVolume = heldByVolume(f, value, policy?.autostop_pct);
    const halt =
      policy === null ? [] : [withDays(rest, " in about {d} days", daysTo(policy.halt_pct, f))];
    return card(byVolume ? PAUSED_BY_VOLUME : way(PAUSED), bar, [...halt, ...accelerated]);
  }
  if (level === 1) {
    const [bar, rest] = splitFirst(NEAR_LINE);
    const days = policy === null ? null : daysTo(policy.autostop_pct, f);
    const headline = way(withDays(NEAR, " · auto-record pauses in about {d} days", days));
    return card(headline, bar, policy === null ? accelerated : [rest, ...accelerated]);
  }
  if (nothing) return card(NOTHING, NOTHING_LINE);
  if (growth !== null && growth <= 0) {
    const measured = historySinceMs !== null && nowMs - historySinceMs >= HOUR_MS;
    return measured
      ? card(STEADY, USAGE, [STEADY_LINE, ...accelerated])
      : card(TOO_EARLY, USAGE, [TOO_EARLY_LINE, ...accelerated]);
  }
  const days = policy === null ? null : daysTo(policy.autostop_pct, f);
  if (days !== null && growth !== null && used !== null) {
    const projection = fill(PROJECTION, {
      "{growth}": formatGrowth(growth),
      "{d}": days,
      "{used30}": `${fixed((used + 30 * growth) / GB, 0)} GB`,
    });
    return card(fill(GROWING, { "{d}": days }), USAGE, [projection, ...accelerated]);
  }
  const until = f.projectedFullAtMs;
  if (until !== null && until > nowMs) {
    // `projected_full_at` is to the nearer wall: the volume when its free space is the smaller.
    const volume =
      f.freeBytes !== null && used !== null && cap !== null && f.freeBytes < cap - used;
    const wall = volume ? BUDGET_WALL.replace(BUDGET_FULL, VOLUME_WALL) : BUDGET_WALL;
    return card(fill(wall, { "{d}": Math.round((until - nowMs) / DAY_MS) }), USAGE, accelerated);
  }
  // Growth is measured, but without the policy no runway can be stated: the headline's state word alone.
  if (growth !== null && growth > 0) return card(head(GROWING), USAGE, accelerated);
  return card(TOO_EARLY, USAGE, [TOO_EARLY_LINE, ...accelerated]);
}

/**
 * The level-3 banner (§3; `role="alert"` once, E16-D06 SR-07): the budget's figures; or the volume's
 * cause, inferred as level 2's is (A-5309-04); or C-8's refused volume.
 */
export function levelThreeBanner(f: DiskFacts, policy: RecorderPolicy | null): string {
  if (f.volumeRefused) return TEXT.levelThreeVolumeRefused;
  if (heldByVolume(f, f.usedBytes, policy?.halt_pct)) return TEXT.levelThreeVolume;
  return fill(TEXT.levelThree, figures(f, 0));
}

/**
 * F-07 (SR-05, SR-06): a level change enters the summary's 10 s batch once, as the card's
 * headline; level 3 speaks as the banner's alert instead (SR-07). Nothing on the first reading.
 */
export function levelChange(previous: DiskLevel | null, card: DiskCard): string | null {
  return previous === null || previous === card.level || card.level === 3 ? null : card.headline;
}
