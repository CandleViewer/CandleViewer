// The eviction planner (26 §7 "Eviction planner", BQ-S15-04). Pure: it maps the loaded bars, the
// visible range, memory.viewportWindowMultiplier and the governor's state to the ranges to drop,
// deterministically for the same input. Whole bars only (a range is the open times of its first and
// last bar, inclusive), never a bar inside the multiplier's window, GPU before CPU (every CPU drop
// is also a GPU drop), CPU only under `over` and only at the edge far from the viewport. Ranges
// already evicted are not planned again. It runs on a governor sample (every 5 s while not `ok`,
// BQ-P2-04), never per frame, so its small result arrays are not a per-frame allocation.
//
// Layers join through `EvictableRegistry.registerEvictable` (internal, not package API): E12-S06
// candles, E18 footprint, E21 heatmap. The runtime wiring is PR-2b.
import type { MemoryState } from "./Governor.js";

/** A run of whole bars: the open times of its first and last bar, inclusive. */
export interface TimeRange {
  readonly fromTime: number;
  readonly toTime: number;
}

/** Where a drop lands: the GPU copy (re-uploaded from the CPU store) or the CPU store (re-fetched). */
export type EvictionTier = "gpu" | "cpu";

export interface EvictionInput {
  /** Bar open times of the loaded (CPU) bars, ascending; only `[0, count)` is read. */
  readonly times: Float64Array;
  readonly count: number;
  /** The visible range (inclusive times, `visibleFrom <= visibleTo`). */
  readonly visibleFrom: number;
  readonly visibleTo: number;
  /** memory.viewportWindowMultiplier (26 §8; [1, 16], default 3). */
  readonly multiplier: number;
  readonly state: MemoryState;
}

export interface EvictionPlan {
  /** GPU drops, far edge first. */
  readonly gpu: readonly TimeRange[];
  /** CPU drops (under `over` only), each also in `gpu` or already GPU-evicted. */
  readonly cpu: readonly TimeRange[];
}

const EMPTY: EvictionPlan = Object.freeze({ gpu: Object.freeze([]), cpu: Object.freeze([]) });

/** First index in `[0, n)` whose time is >= t (n when none). */
function lowerBound(times: Float64Array, n: number, t: number): number {
  let lo = 0;
  let hi = n;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((times[mid] as number) < t) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** First index in `[0, n)` whose time is > t (n when none). */
function upperBound(times: Float64Array, n: number, t: number): number {
  let lo = 0;
  let hi = n;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((times[mid] as number) <= t) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * The multiplier's window around the visible range: `multiplier × span` wide, centred on it, so
 * `(multiplier - 1) / 2` spans each side. A zero span (one bar) keeps that bar only.
 */
export function evictionWindow(
  visibleFrom: number,
  visibleTo: number,
  multiplier: number,
): TimeRange {
  const pad = ((visibleTo - visibleFrom) * (multiplier - 1)) / 2;
  return { fromTime: visibleFrom - pad, toTime: visibleTo + pad };
}

/** Index runs `[a, b]` (inclusive) of `[lo, hi]` not covered by any of `evicted`. */
function subtract(
  times: Float64Array,
  n: number,
  lo: number,
  hi: number,
  evicted: readonly TimeRange[],
): [number, number][] {
  let runs: [number, number][] = lo <= hi ? [[lo, hi]] : [];
  for (const r of evicted) {
    const a = lowerBound(times, n, r.fromTime);
    const b = upperBound(times, n, r.toTime) - 1;
    if (a > b) continue;
    const next: [number, number][] = [];
    for (const [x, y] of runs) {
      if (b < x || a > y) next.push([x, y]);
      else {
        if (x < a) next.push([x, a - 1]);
        if (b < y) next.push([b + 1, y]);
      }
    }
    runs = next;
  }
  return runs;
}

/**
 * Plans the drops. `evictedGpu` / `evictedCpu` are the ranges already dropped at each tier (an
 * `EvictionLedger`'s), which are never planned again. Invalid input (non-finite or inverted
 * visible range, multiplier < 1, no bars) plans nothing.
 */
export function planEviction(
  input: EvictionInput,
  evictedGpu: readonly TimeRange[] = [],
  evictedCpu: readonly TimeRange[] = [],
): EvictionPlan {
  const { times, visibleFrom, visibleTo, multiplier, state } = input;
  const n = Math.min(input.count, times.length);
  if (
    state === "ok" ||
    !(n > 0) ||
    !Number.isFinite(visibleFrom) ||
    !Number.isFinite(visibleTo) ||
    visibleTo < visibleFrom ||
    !Number.isFinite(multiplier) ||
    multiplier < 1
  ) {
    return EMPTY;
  }
  const w = evictionWindow(visibleFrom, visibleTo, multiplier);
  // Before the window: bar i with a successor opening at or before the window's start (the last
  // loaded bar has no successor, so it is never wholly before). After: opening past its end.
  // leftHi < rightLo always, as the window's start is not after its end.
  const leftHi = upperBound(times, n, w.fromTime) - 2;
  const rightLo = upperBound(times, n, w.toTime);
  const toRange = ([a, b]: [number, number]): TimeRange => ({
    fromTime: times[a] as number,
    toTime: times[b] as number,
  });
  const left = subtract(times, n, 0, leftHi, evictedGpu).map(toRange);
  const right = subtract(times, n, rightLo, n - 1, evictedGpu).map(toRange);
  // Far edge first: the side whose loaded end is further from the visible range (ties: older).
  const leftFar = visibleFrom - (times[0] as number) >= (times[n - 1] as number) - visibleTo;
  right.reverse();
  const gpu = leftFar ? [...left, ...right] : [...right, ...left];
  if (state !== "over") return { gpu, cpu: [] };
  const cpu = leftFar
    ? subtract(times, n, 0, leftHi, evictedCpu).map(toRange)
    : subtract(times, n, rightLo, n - 1, evictedCpu)
        .map(toRange)
        .reverse();
  return { gpu, cpu };
}
