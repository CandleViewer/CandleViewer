// Seeded, hand-rolled generators for the memory planner's property tests (BQ-S15-04 rider: no
// fast-check in the package; a dependency into chart-engine needs an ADR). mulberry32 gives the same
// sequence on every platform, so a failing seed reproduces exactly.
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import type { EvictionInput, TimeRange } from "../../src/memory/EvictionPlanner.js";
import type { MemoryState } from "../../src/memory/Governor.js";

export interface Gen {
  int(lo: number, hi: number): number;
  pick<T>(xs: readonly T[]): T;
}

export function gen(seed: number): Gen {
  const rng = mulberry32(seed);
  return {
    int: (lo, hi) => {
      const a = Math.ceil(lo);
      return a + Math.floor(rng() * (Math.floor(hi) - a + 1));
    },
    pick: (xs) => xs[Math.floor(rng() * xs.length)] as never,
  };
}

const STATES: readonly MemoryState[] = ["ok", "pressure", "over"];

/**
 * Loaded bars at a fixed or jittered step (gaps like a weekend or a halt), a visible range inside,
 * around or past them, and a multiplier in [1, 16]. Times are integers (µs-like).
 */
export function evictionInput(g: Gen, state?: MemoryState): EvictionInput {
  const count = g.int(1, 400);
  const step = g.pick([1, 60, 60_000_000]);
  const times = new Float64Array(count + g.int(0, 8)); // slack past `count` is never read
  let t = g.int(-1000, 1000) * step;
  for (let i = 0; i < times.length; i += 1) {
    times[i] = t;
    t += step * (g.int(0, 9) === 0 ? g.int(2, 50) : 1);
  }
  const first = times[0] as number;
  const last = times[count - 1] as number;
  const span = last - first;
  const a = first + g.int(-span / 4, (span * 5) / 4);
  const b = a + g.int(0, Math.max(1, span / 3));
  return {
    times,
    count,
    visibleFrom: a,
    visibleTo: b,
    multiplier: g.int(1, 16),
    state: state ?? g.pick(STATES),
  };
}

/** Bar indices `[0, count)` a range covers. */
export function indicesIn(input: EvictionInput, r: TimeRange): number[] {
  const out: number[] = [];
  for (let i = 0; i < input.count; i += 1) {
    const t = input.times[i] as number;
    if (t >= r.fromTime && t <= r.toTime) out.push(i);
  }
  return out;
}
