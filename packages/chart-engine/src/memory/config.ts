// Memory constants (26 §7/§8, E11-S15): the F-08 ceilings `createChart` checks before mounting, and
// the per-view default lookbacks the app's `memory.defaultLookbackDays` setting overrides.

/** 2,097,152 bars: a 2^22-slot BarStore at its ceiling capacity, 132 MiB (F-08, BQ-S15-09). */
export const MAX_BARS_CEILING = 2 ** 21;
/** The largest `memoryBudgetMb` a chart accepts (MiB, F-08). */
export const MEMORY_BUDGET_CEILING_MB = 4096;
/** The smallest: one default framebuffer plus the atlas must fit (MiB, a guard, not a working size). */
export const MEMORY_BUDGET_FLOOR_MB = 64;

/** Days of history per view (BQ-S15-11; values PROPOSED, awaiting the owner). */
export const DEFAULT_LOOKBACK_DAYS: Readonly<{ chart: 30; footprint: 3; profile: 7; replay: 1 }> =
  Object.freeze({ chart: 30, footprint: 3, profile: 7, replay: 1 });

/** Throws `RangeError` unless `value` is undefined or an integer in [min, max]; returns it or `fallback`. */
export function boundedInt(
  value: number | undefined,
  fallback: number,
  min: number,
  max: number,
  name: string,
): number {
  if (value === undefined) return fallback;
  if (!Number.isSafeInteger(value) || value < min || value > max) {
    throw new RangeError(`chart-engine: ${name} must be an integer in [${min}, ${max}]`);
  }
  return value;
}

/** `memory.viewportWindowMultiplier` default: the eviction window is 3 visible spans (26 §7, §8). */
export const VIEWPORT_WINDOW_MULTIPLIER = 3;
/** Its accepted range at `createChart`, [1, 16] (BQ-P2-08, 26 §7 internal constants). */
export const VIEWPORT_WINDOW_MULTIPLIER_MAX = 16;
