// E24-S06 (#781) slice 1: the per-bar liquidation notional model. The story's correctness trap (ticket technical
// notes; D02 §6 F18; D03 S54-45 / S54-47) is that a bar with no recorded data is NOT a bar with no liquidations:
// zero and unknown are separate states here and stay separate in the table, the readout and, later, the plot.
// BQ-2 (ruled 6618707867): `/market/metrics` reads "0" for a bar without prints and carries no coverage, so the
// mask is client-side from #780's single `/market/liquidations` `meta.coverage` read (`first_available_ts`),
// never from the first non-empty bucket. Recorder gaps stay with S05's chip: no second read, no gap drawn.
// Values are the served decimal strings, never a float; nothing is summed or re-bucketed (BQ-10): a bar is the
// metrics series' own `t`.
import type { LiqCoverage } from "../history";

export type BarState = "recorded" | "zero" | "unknown";

export interface LiqBar {
  /** The bar's open time, epoch ms: the price chart's own bar `t` (BQ-10). */
  readonly tMs: number;
  readonly state: BarState;
  /** Long-liquidated notional, USDT, as served; `null` exactly when the bar is `unknown`. */
  readonly long: string | null;
  /** Short-liquidated notional, USDT, as served; `null` exactly when the bar is `unknown`. */
  readonly short: string | null;
  /**
   * PROPOSED: set on a recorded bar that opens before the recorder began: the figures cover only the bar's
   * recorded part, from this time (epoch ms). `null` for every other bar.
   */
  readonly partialFromMs: number | null;
}

/** `tMs` to its served value; `null`: the server sent no number for the bar (never read as 0). */
export type SidePoints = ReadonlyMap<number, string | null>;

const DECIMAL = /^\d+(?:\.\d+)?$/;
const ZERO = /^0+(?:\.0+)?$/;

/** A served notional (a non-negative decimal string) or `null`. */
export const asNotional = (v: unknown): string | null =>
  typeof v === "string" && DECIMAL.test(v) ? v : null;

export const isZero = (decimal: string): boolean => ZERO.test(decimal);

/**
 * Where the bar `[tMs, tMs + intervalMs)` sits against the recorder's first stored print: `outside` it closes at or
 * before it, `straddles` it opens before it and closes after, `inside` it opens at or after it.
 */
export function recordedPosition(
  tMs: number,
  intervalMs: number,
  coverage: LiqCoverage,
): "outside" | "straddles" | "inside" {
  const first = coverage.firstAvailableMs;
  if (first === null || tMs + intervalMs <= first) return "outside";
  return tMs < first ? "straddles" : "inside";
}

/**
 * The state of one bar. `unknown` before the recorder began, for a bar the server sent no number for, and for a
 * bar that straddles the first print and reads zero (PROPOSED: zero there is only a claim about part of the bar,
 * and a false "no liquidations" is the one error this story must not make; a non-zero straddling bar is the
 * recorded part, shown as served). Both sides zero is `zero`; one side zero beside a positive one is `recorded`.
 */
export function barState(
  tMs: number,
  intervalMs: number,
  coverage: LiqCoverage,
  long: string | null,
  short: string | null,
): LiqBar {
  const unknown: LiqBar = { tMs, state: "unknown", long: null, short: null, partialFromMs: null };
  if (long === null || short === null) return unknown;
  const where = recordedPosition(tMs, intervalMs, coverage);
  if (where === "outside") return unknown;
  const zero = isZero(long) && isZero(short);
  if (zero && where === "straddles") return unknown;
  const partialFromMs = where === "straddles" ? coverage.firstAvailableMs : null;
  return { tMs, state: zero ? "zero" : "recorded", long, short, partialFromMs };
}

/** One bar per `t` either side served, ascending; a side that omits a `t` is `null` there (so `unknown`). */
export function buildBars(
  long: SidePoints,
  short: SidePoints,
  coverage: LiqCoverage,
  intervalMs: number,
): LiqBar[] {
  const times = [...new Set([...long.keys(), ...short.keys()])].sort((a, b) => a - b);
  return times.map((t) =>
    barState(t, intervalMs, coverage, long.get(t) ?? null, short.get(t) ?? null),
  );
}

/** The bar whose span holds `atMs` (the crosshair), or `null`. */
export function barAt(bars: readonly LiqBar[], atMs: number, intervalMs: number): LiqBar | null {
  return bars.find((b) => atMs >= b.tMs && atMs < b.tMs + intervalMs) ?? null;
}

/** BQ-10: the series' bars against the price chart's, by `t`: no re-bucketing, so any difference is a defect. */
export function gridDifference(
  bars: readonly LiqBar[],
  priceBarTimes: readonly number[],
): { readonly missing: number[]; readonly extra: number[] } {
  const have = new Set(bars.map((b) => b.tMs));
  const want = new Set(priceBarTimes);
  return {
    missing: priceBarTimes.filter((t) => !have.has(t)),
    extra: bars.map((b) => b.tMs).filter((t) => !want.has(t)),
  };
}

export type Boundary =
  /** The recorder began inside the window: the labelled marker (D03 S54-45), positioned at `atMs`. */
  | { readonly kind: "in-view"; readonly atMs: number }
  /** The whole window precedes the first stored print: every bar is `unknown` (S54-47). */
  | { readonly kind: "before"; readonly atMs: number }
  /** Nothing is stored for the symbol (S54-46). */
  | { readonly kind: "never" }
  /** The window starts at or after the first stored print: no boundary to draw. */
  | { readonly kind: "none" };

/** The marker comes from `first_available_ts`, never from the first non-empty bucket (the ticket). */
export function boundaryOf(coverage: LiqCoverage, fromMs: number, toMs: number): Boundary {
  const first = coverage.firstAvailableMs;
  if (first === null) return { kind: "never" };
  // `first_available_ts` alone decides (BQ-2): the window ends before it, or it does not
  if (first >= toMs) return { kind: "before", atMs: first };
  return first > fromMs ? { kind: "in-view", atMs: first } : { kind: "none" };
}

// The history bound: `22` `/market/metrics` (#5341): a window of at most 1,500 bars and 400 days is served, a wider
// one is `400 invalid_time_range`; the server's default is 500 bars before `to`.
export const MAX_WINDOW_BARS = 1500;
export const MAX_WINDOW_DAYS = 400;
export const DEFAULT_WINDOW_BARS = 500;
const DAY_MS = 86_400_000;

export interface BarWindow {
  readonly fromMs: number;
  readonly toMs: number;
  /** Bars the window can hold: what the bound left of the ask. */
  readonly bars: number;
}

/** The newest `bars` bars up to `nowMs`, aligned to the grid, within both bounds. */
export function barWindow(
  nowMs: number,
  intervalMs: number,
  bars: number = DEFAULT_WINDOW_BARS,
): BarWindow {
  const count = Math.max(
    1,
    Math.min(bars, MAX_WINDOW_BARS, Math.floor((MAX_WINDOW_DAYS * DAY_MS) / intervalMs)),
  );
  const open = Math.floor(nowMs / intervalMs) * intervalMs;
  return { fromMs: open - (count - 1) * intervalMs, toMs: nowMs, bars: count };
}

/** `22`'s `bar_type=time` `param` codes (`bars/spec.py` `TIME_INTERVALS`): the minutes, then `D` and `W`. */
const MINUTE_MS = 60_000;
export const TIME_PARAMS: Readonly<Record<string, number>> = {
  ...Object.fromEntries(
    ["1", "3", "5", "15", "30", "60", "120", "240", "360", "720"].map((m) => [
      m,
      Number(m) * MINUTE_MS,
    ]),
  ),
  D: 1440 * MINUTE_MS,
  W: 7 * 1440 * MINUTE_MS,
};
