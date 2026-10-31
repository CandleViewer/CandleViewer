/**
 * Snooze math (E40-S01): a preset or a picked instant becomes the `until` of
 * `PUT /alerts/{alertId}/snooze`. The clock is injected. A past or non-finite instant is refused
 * here, before the request, mirroring the server's `422 validation_failed` (including its 30-day cap) (the server stays the
 * authority). The wire value is a tz-aware UTC ISO string, as the contract requires.
 */
export type SnoozePreset = "15m" | "1h" | "4h" | "24h";

const MINUTE_MS = 60_000;
export const SNOOZE_PRESET_MS: Readonly<Record<SnoozePreset, number>> = {
  "15m": 15 * MINUTE_MS,
  "1h": 60 * MINUTE_MS,
  "4h": 240 * MINUTE_MS,
  "24h": 1_440 * MINUTE_MS,
};
/** The server refuses a snooze reaching further than this (`until_too_far`). */
export const SNOOZE_MAX_MS = 30 * 1_440 * MINUTE_MS;
export const SNOOZE_PRESETS: readonly SnoozePreset[] = ["15m", "1h", "4h", "24h"];

export interface SnoozeClock {
  readonly now: () => number;
}

export type SnoozeResult =
  | { readonly ok: true; readonly until: string }
  | { readonly ok: false; readonly reason: "past" | "invalid" | "too_far" };

export function snoozeFromPreset(preset: SnoozePreset, clock: SnoozeClock): SnoozeResult {
  return snoozeUntil(clock.now() + SNOOZE_PRESET_MS[preset], clock);
}

/** `untilMs` is epoch ms. Equal to now counts as past: a snooze must end strictly later. */
export function snoozeUntil(untilMs: number, clock: SnoozeClock): SnoozeResult {
  if (!Number.isFinite(untilMs)) return { ok: false, reason: "invalid" };
  if (untilMs <= clock.now()) return { ok: false, reason: "past" };
  if (untilMs > clock.now() + SNOOZE_MAX_MS) return { ok: false, reason: "too_far" };
  return { ok: true, until: new Date(untilMs).toISOString() };
}

/** For a picked ISO string; an offset-less or unparseable string is invalid. */
export function snoozeFromIso(iso: string, clock: SnoozeClock): SnoozeResult {
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(iso)) return { ok: false, reason: "invalid" };
  return snoozeUntil(Date.parse(iso), clock);
}
