import type { StateId } from "./states";

/**
 * Client-computed thresholds, each with its E08-D09 Q-id and value (E08-S12 ruling, cross-BQ 4). A trigger
 * D09 gives no figure for reads S-19; no figure is invented here.
 */
export const THRESHOLDS = {
  /** D09-Q1: S-02 when used now >= 80 % of the spendable limit (PROPOSED). */
  nearLimitPct: 80,
  /** D09-Q2: S-08 when resubscribes exceed 1 within 5 s (PROPOSED). */
  resubscribeStormCount: 1,
  resubscribeStormWindowMs: 5_000,
  /** D09-Q6: S-15 when a value's "as of" is more than 5 s old (PROPOSED). */
  staleAfterMs: 5_000,
  /** D09 §5.2 S-15 (`clock`:132): a clock row's "as of" is stale only past 900 s; it is measured about every 5 minutes. */
  clockStaleAfterMs: 900_000,
  /** D09-Q8: S-20 when a drop counter rose within the last 60 s (PROPOSED). */
  dropWindowMs: 60_000,
  /** D09-Q9: an episode ends once its state has been exited for 5 s (PROPOSED). */
  episodeCloseMs: 5_000,
  /** D09-Q9: entries of one state within 1 s join one line (PROPOSED). */
  episodeJoinMs: 1_000,
  /** D09 §5.2 S-09, from the clock guard (`clock`:129): the offset's size above this warns. */
  clockWarnMs: 500,
  /** D09 §5.2 S-10, from the clock guard (`clock`:130): above this, order entry halts. */
  clockHaltMs: 2_000,
} as const;

/**
 * Highest severity first, one state per row (E08-D09 §5.2, "Precedence on one row"). The order is RULED
 * (BQ-07, D09 :278); E08-D13 §5.4 carries none of its own. S-13 and the flag come before the table. Only
 * S-14's place (before S-19) is PROPOSED: D09's list omits S-14.
 */
export const PRECEDENCE: readonly StateId[] = [
  "S-05", "S-04", "S-10", "S-11", "S-06", "S-03", "S-07", "S-08", "S-20", "S-09",
  "S-02", "S-17", "S-18", "S-16", "S-15", "S-12", "S-14", "S-19", "S-01",
] as const; // prettier-ignore

/** How a slice's read stands: the served `AdminSliceStatus` words, a failed read, or none yet. */
export type ReadStatus = "loading" | "ok" | "error" | "unavailable" | "failed" | "none";

export type Connection = "connected" | "reconnecting" | "disconnected";

/**
 * What the selector may know. A field left out is a figure the server does not serve: it can only fall
 * through to S-19 (R-2), never read as a calm default.
 */
export interface StateSignals {
  /** The slice's build flag; off reads S-19. */
  readonly enabled: boolean;
  readonly read: ReadStatus;
  /** Slices of the page that read `error` / `ok` (S-16 needs both). */
  readonly errorSlices?: number;
  readonly okSlices?: number;
  /** Served `10006`, `10018` or lockout state (D09-G1, G13). */
  readonly throttled?: boolean;
  readonly ipHold?: boolean;
  readonly banned?: boolean;
  readonly connection?: Connection;
  /** Resubscribes seen inside the last `resubscribeStormWindowMs`. */
  readonly resubscribesInWindow?: number;
  /** The clock offset in ms (signed); `null` or left out is unmeasured. */
  readonly clockOffsetMs?: number | null;
  /** A served `10002` refusal not yet cleared by a resync. */
  readonly refused10002?: boolean;
  /** Used now as a percentage of the SPENDABLE limit; only when served. */
  readonly usedPctOfSpendable?: number;
  /** Age of the "as of" in ms. */
  readonly asOfAgeMs?: number;
  /** The "as of" belongs to the clock measurement, so S-15 waits for `clockStaleAfterMs`, not `staleAfterMs`. */
  readonly asOfIsClock?: boolean;
  /** A drop counter rose inside `dropWindowMs`. */
  readonly dropped?: boolean;
  /** A served inspector read with this many topics. */
  readonly inspectorTopics?: number;
}

const finite = (n: number | null | undefined): n is number =>
  typeof n === "number" && Number.isFinite(n);

/** Every state whose trigger holds for these signals, in no order. */
export function activeStates(s: StateSignals): ReadonlySet<StateId> {
  const on = new Set<StateId>();
  if (s.banned === true) on.add("S-05");
  if (s.ipHold === true) on.add("S-04");
  if (s.throttled === true) on.add("S-03");
  if (s.refused10002 === true) on.add("S-11");
  if (s.connection === "disconnected") on.add("S-06");
  if (s.connection === "reconnecting") on.add("S-07");
  if ((s.resubscribesInWindow ?? 0) > THRESHOLDS.resubscribeStormCount) on.add("S-08");
  if (s.dropped === true) on.add("S-20");
  if (s.clockOffsetMs === null) on.add("S-12");
  if (finite(s.clockOffsetMs)) {
    const size = Math.abs(s.clockOffsetMs);
    if (size > THRESHOLDS.clockHaltMs) on.add("S-10");
    else if (size > THRESHOLDS.clockWarnMs) on.add("S-09");
  }
  if (finite(s.usedPctOfSpendable) && s.usedPctOfSpendable >= THRESHOLDS.nearLimitPct)
    on.add("S-02");
  if (s.read === "error") on.add("S-17");
  if (s.read === "failed") on.add("S-18");
  if ((s.errorSlices ?? 0) > 0 && (s.okSlices ?? 0) > 0) on.add("S-16");
  const staleLimit =
    s.asOfIsClock === true ? THRESHOLDS.clockStaleAfterMs : THRESHOLDS.staleAfterMs;
  if (finite(s.asOfAgeMs) && s.asOfAgeMs > staleLimit) on.add("S-15");
  if (s.inspectorTopics === 0) on.add("S-14");
  if (s.read === "unavailable" || s.read === "none") on.add("S-19");
  // Healthy only when every figure is served and the spendable share is known to sit below S-02's line.
  if (
    s.read === "ok" &&
    finite(s.usedPctOfSpendable) &&
    s.usedPctOfSpendable < THRESHOLDS.nearLimitPct
  )
    on.add("S-01");
  return on;
}

/** The one state a row shows: off reads S-19, a first read in flight S-13, else the highest precedence. */
export function selectConnectivityState(s: StateSignals): StateId {
  if (!s.enabled) return "S-19";
  if (s.read === "loading") return "S-13";
  const on = activeStates(s);
  for (const id of PRECEDENCE) if (on.has(id)) return id;
  return "S-19";
}
