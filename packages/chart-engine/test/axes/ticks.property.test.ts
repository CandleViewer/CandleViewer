// E11-S06 tick-model properties (README BQ-186, BQ-187, BQ-189, BQ-203), seeded mulberry32 loops
// as BQ-81 rules for this package (no fast-check dependency). Price: candidates strictly ascending
// in value and descending in y, inside the window plus its hidden margin, whole-tick multiples of
// one `{1, 2, 5} × 10^n` step. Time: candidates strictly ascending, a ladder step that clears the
// gap, each ranked at or above the step, and a rank that is monotone along the step's divisibility
// chain. A failure prints its seed.
import { describe, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { TickSet } from "../../src/axes/decimate.js";
import { civil, createZoned, ZoneClock } from "../../src/axes/format.js";
import { MARGIN_GAPS, PriceTicks } from "../../src/axes/price-ticks.js";
import { RANK, rankOf, TIME_LADDER, TimeTicks } from "../../src/axes/time-ticks.js";
import { ChartViewport } from "../../src/viewport/index.js";

const CASES = 10_000;
/** A TimeTicks pass reads a zone's formatter for each new hour: fewer cases keep it quick. */
const TIME_CASES = 1_000;
const BASE = 387_000;
const GAP = 40;

function forAll(cases: number, check: (rng: () => number) => void): void {
  for (let c = 0; c < cases; c += 1) {
    const rng = mulberry32(BASE + c);
    try {
      check(rng);
    } catch (e) {
      throw new Error(`seed ${BASE + c}: ${(e as Error).message}`);
    }
  }
}

/** A plain check: `expect` per candidate costs more than the model under test. */
function ok(cond: boolean, what: string): void {
  if (!cond) throw new Error(what);
}

const pick = <T>(rng: () => number, xs: readonly T[]): T => xs[Math.floor(rng() * xs.length)] as T;

describe("price-ticks properties", () => {
  it(
    "candidates are ascending, in the window, whole-tick multiples of a {1, 2, 5} step",
    { timeout: 60_000 },
    () => {
      forAll(CASES, (rng) => {
        const tick = pick(rng, [1e-6, 0.01, 0.1, 0.5, 1]);
        const low = (0.001 + rng() * 100_000) / tick;
        const high = low + 20 + rng() * Math.min(1e6, low * 3);
        const height = 200 + rng() * 700;
        const vp = new ChartViewport();
        vp.setSize(1200, 1000, 1);
        vp.setPanePlot(0, 0, height);
        vp.setPriceInfo(0, 0, tick);
        vp.setPriceRange(0, low, high);
        const set = new TickSet();
        new PriceTicks().update(vp, 0, 0, height, GAP, 13, set);
        ok(set.n > 0, "no candidates");
        const margin = MARGIN_GAPS * GAP;
        for (let i = 0; i < set.n; i += 1) {
          const y = set.at[i] as number;
          ok(y >= -margin - 1e-6 && y <= height + margin + 1e-6, `y ${y} outside the window`);
          ok(Number.isInteger(set.value[i]), `value ${set.value[i]} is not a whole tick`);
          if (i === 0) continue;
          ok((set.value[i] as number) > (set.value[i - 1] as number), "values not ascending");
          ok(y < (set.at[i - 1] as number), "a higher price is not higher on screen");
        }
        if (set.n < 2) return;
        const step = (set.value[1] as number) - (set.value[0] as number);
        const mantissa = Math.round(step / 10 ** Math.floor(Math.log10(step)));
        ok(mantissa === 1 || mantissa === 2 || mantissa === 5, `step ${step} is off the ladder`);
        for (let i = 0; i < set.n; i += 1) {
          ok(Number.isInteger((set.value[i] as number) / step), `value ${set.value[i]} off step`);
        }
      });
    },
  );
});

/** The sub-day steps from `from` upward that each divide the next (time-ticks.ts's chain). */
function chain(from: number): number[] {
  const out = [from];
  for (let i = from + 1; i < RANK.day; i += 1) {
    const last = TIME_LADDER[out[out.length - 1] as number] as number;
    if ((TIME_LADDER[i] as number) % last === 0) out.push(i);
  }
  return out;
}

describe("time-ticks properties", () => {
  it(
    "a sub-day rank reaches its step exactly on the step's marks, monotone along the chain",
    { timeout: 60_000 },
    () => {
      const z = createZoned();
      forAll(CASES, (rng) => {
        civil(Math.floor(rng() * 40_000) - 10_000, z);
        z.ms = Math.floor(rng() * 86_400) * 1000;
        if (rng() < 0.3) z.ms -= z.ms % pick(rng, [60_000, 900_000, 3_600_000]); // round marks
        const a = Math.floor(rng() * RANK.day);
        const step = TIME_LADDER[a] as number;
        ok(rankOf(z, a) >= a === (z.ms === 0 || z.ms % step === 0), `rank at step ${a}`);
        for (const b of chain(a)) {
          ok(rankOf(z, a) >= b === rankOf(z, b) >= b, `rank at ${a} vs ${b}`);
        }
      });
    },
  );

  it(
    "candidates ascend in time and x, on a ladder step that clears the gap, ranked ≥ it",
    { timeout: 60_000 },
    () => {
      const zones = ["UTC", "America/New_York", "Asia/Kolkata", "Australia/Lord_Howe"];
      const clocks = new Map(zones.map((zone) => [zone, new ZoneClock(zone)]));
      forAll(TIME_CASES, (rng) => {
        const barUs = pick(rng, [1e6, 60e6, 300e6, 3_600e6, 86_400e6]);
        const n = 20_000;
        const t0 = Date.UTC(2020, 0, 1) * 1000 + Math.floor(rng() * 1e5) * 60e6;
        const vp = new ChartViewport({
          length: n,
          barDurationUs: barUs,
          indexToTime: (i) => (i >= 0 && i < n ? t0 + i * barUs : Number.NaN),
          timeToIndex: (t) => (t < t0 ? -1 : Math.min(n - 1, Math.floor((t - t0) / barUs))),
        });
        vp.setSize(1200, 600, 1);
        const spacing = 0.05 * 1200 ** rng(); // 0.05 to 60 px a bar, log-uniform
        vp.scrollTo(Math.floor(n / 4 + rng() * (n / 2)), spacing);
        const clock = clocks.get(pick(rng, zones)) as ZoneClock;
        const ticks = new TimeTicks(clock);
        const set = new TickSet();
        ticks.update(vp, 1200, GAP * 2, (t) => t.length * 6.6, set);
        const s = ticks.step;
        ok(s >= 0 && s < TIME_LADDER.length, `step ${s}`);
        const pxPerMs = spacing / (barUs / 1000);
        if (s < TIME_LADDER.length - 1) {
          ok((TIME_LADDER[s] as number) * pxPerMs >= GAP * 2 - 1e-9, "the step misses the gap");
        }
        const z = createZoned();
        for (let i = 0; i < set.n; i += 1) {
          const t = set.value[i] as number;
          ok((set.rank[i] as number) >= s, `rank ${set.rank[i]} under step ${s}`);
          ok(set.rank[i] === rankOf(clock.fields(t, z), s), `rank of ${t}`);
          if (i === 0) continue;
          ok(t > (set.value[i - 1] as number), "times not ascending");
          ok((set.at[i] as number) > (set.at[i - 1] as number), "x not ascending");
        }
      });
    },
  );
});
