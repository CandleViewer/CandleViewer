import type { CopyKey } from "./copy";
import { parts } from "./text";

/** SCR-147's twenty states (E08-D09 §5.2; E08-D13 §5.4). */
export const STATE_IDS = [
  "S-01", "S-02", "S-03", "S-04", "S-05", "S-06", "S-07", "S-08", "S-09", "S-10",
  "S-11", "S-12", "S-13", "S-14", "S-15", "S-16", "S-17", "S-18", "S-19", "S-20",
] as const; // prettier-ignore

export type StateId = (typeof STATE_IDS)[number];

/** CMP-178's glyph shapes (`15`:2230). */
export type Glyph = "check" | "triangle" | "octagon" | "clock" | "ring";
/** CMP-178's tone for a glyph; the clock glyph is the `stale` tone. */
export type Tone = "ok" | "warning" | "danger" | "stale" | "neutral";
export type Origin = "Exchange" | "Network" | "Our backend" | null;
export type AnnounceClass = "never" | "polite" | "assertive";

export interface StateSpec {
  readonly id: StateId;
  /** The deck entry that carries the state's word and sentences. */
  readonly copy: CopyKey | null;
  readonly origin: Origin;
  readonly glyph: Glyph;
  readonly announce: AnnounceClass;
  /** `true`: at most once per episode; `false`: at most once per 5 s per region (§5.2 `max_rate`). */
  readonly oncePerEpisode: boolean;
}

const GLYPH_TONE: Readonly<Record<Glyph, Tone>> = {
  check: "ok",
  triangle: "warning",
  octagon: "danger",
  clock: "stale",
  ring: "neutral",
};

const row = (
  id: StateId,
  copy: CopyKey | null,
  origin: Origin,
  glyph: Glyph,
  announce: AnnounceClass,
  oncePerEpisode = false,
): StateSpec => ({ id, copy, origin, glyph, announce, oncePerEpisode });

/** The register, row for row with E08-D09 §5.2 (word, glyph, origin, announcement class, `max_rate`). */
export const STATES: Readonly<Record<StateId, StateSpec>> = {
  "S-01": row("S-01", "W-13", null, "check", "never"),
  "S-02": row("S-02", "W-14", "Exchange", "triangle", "polite"),
  "S-03": row("S-03", "W-15", "Exchange", "triangle", "polite", true),
  "S-04": row("S-04", "W-16", "Exchange", "clock", "polite", true),
  "S-05": row("S-05", "W-17", "Exchange", "octagon", "polite", true),
  "S-06": row("S-06", "W-18", "Network", "octagon", "assertive", true),
  "S-07": row("S-07", "W-19", "Network", "ring", "polite"),
  "S-08": row("S-08", "W-20", "Network", "triangle", "polite"),
  "S-09": row("S-09", "W-21", "Our backend", "triangle", "polite"),
  "S-10": row("S-10", "W-22", "Our backend", "octagon", "polite", true),
  "S-11": row("S-11", "W-22", "Exchange", "octagon", "polite", true),
  "S-12": row("S-12", "W-23", "Our backend", "triangle", "polite"),
  "S-13": row("S-13", null, null, "ring", "never"),
  "S-14": row("S-14", "W-30", null, "ring", "never"),
  "S-15": row("S-15", "W-04", "Our backend", "clock", "never"),
  "S-16": row("S-16", "W-24", "Our backend", "triangle", "polite"),
  "S-17": row("S-17", "W-25", "Our backend", "octagon", "polite"),
  "S-18": row("S-18", "W-26", "Our backend", "octagon", "polite"),
  "S-19": row("S-19", "W-05", null, "ring", "never"),
  "S-20": row("S-20", "W-28", "Our backend", "triangle", "polite"),
};

export const toneOf = (id: StateId): Tone => GLYPH_TONE[STATES[id].glyph];

/** The state's word: the deck entry's first line; S-13's is visually hidden (§5.2). */
export function wordOf(id: StateId): string {
  const key = STATES[id].copy;
  if (key === null) return "Loading";
  return parts(key)[0] ?? "";
}
