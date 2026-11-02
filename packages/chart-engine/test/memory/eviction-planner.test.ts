// E11-S15 PR-2a: the eviction planner (26 §7 "Eviction planner", BQ-S15-04), the registry seam and
// the ledger. Example cases pin the window arithmetic and the far-edge order; the property cases
// (seeded, hand-rolled generators in ./gen.ts) hold the invariants over 500 seeds each.
import { describe, expect, it, vi } from "vitest";
import { EvictableRegistry, EvictionLedger } from "../../src/memory/Evictables.js";
import {
  evictionWindow,
  planEviction,
  type EvictionInput,
  type TimeRange,
} from "../../src/memory/EvictionPlanner.js";
import { evictionInput, gen, indicesIn } from "./gen.js";

/** Bars at times 0..n-1 (one per unit), the visible range [a, b]. */
const unit = (n: number, a: number, b: number, state: EvictionInput["state"], m = 3) => ({
  times: Float64Array.from({ length: n }, (_, i) => i),
  count: n,
  visibleFrom: a,
  visibleTo: b,
  multiplier: m,
  state,
});
const r = (fromTime: number, toTime: number): TimeRange => ({ fromTime, toTime });

describe("Scenario: memory use crosses the pressure threshold — GPU evicted outside the 3x window (AC3)", () => {
  it("the window is multiplier x the visible span, centred on it", () => {
    expect(evictionWindow(100, 110, 3)).toEqual(r(90, 120));
    expect(evictionWindow(100, 110, 1)).toEqual(r(100, 110));
    expect(evictionWindow(100, 100, 16)).toEqual(r(100, 100));
  });

  it("pressure drops GPU ranges on both sides of the window, far edge first, CPU kept", () => {
    // 100 bars, visible [60, 70], window [50, 80]: bar 49 ends at 50 (wholly before), bar 80 is in.
    const plan = planEviction(unit(100, 60, 70, "pressure"));
    expect(plan).toEqual({ gpu: [r(0, 49), r(81, 99)], cpu: [] });
  });

  it("over also drops the CPU range at the edge far from the viewport only", () => {
    expect(planEviction(unit(100, 60, 70, "over")).cpu).toEqual([r(0, 49)]);
    // Viewport near the start: the far edge is the right one, listed first.
    expect(planEviction(unit(100, 10, 20, "over"))).toEqual({
      gpu: [r(31, 99)],
      cpu: [r(31, 99)],
    });
  });

  it("ok plans nothing, nor does invalid input", () => {
    expect(planEviction(unit(100, 60, 70, "ok"))).toEqual({ gpu: [], cpu: [] });
    for (const bad of [
      unit(0, 60, 70, "over"),
      unit(100, 70, 60, "over"),
      unit(100, Number.NaN, 70, "over"),
      unit(100, 60, Infinity, "over"),
      unit(100, 60, 70, "over", 0.5),
      unit(100, 60, 70, "over", Number.NaN),
    ]) {
      expect(planEviction(bad)).toEqual({ gpu: [], cpu: [] });
    }
  });

  it("never plans a range already evicted, splitting around it", () => {
    const plan = planEviction(unit(100, 60, 70, "over"), [r(10, 19), r(90, 99)], [r(0, 4)]);
    expect(plan.gpu).toEqual([r(0, 9), r(20, 49), r(81, 89)]);
    expect(plan.cpu).toEqual([r(5, 49)]);
    expect(planEviction(unit(100, 60, 70, "pressure"), [r(-5, 200)]).gpu).toEqual([]);
  });

  it("a bar reaching into the window is kept, and the last bar is never wholly before", () => {
    // Bars at 0, 10, 20; window [25, 35]: bar 20 (ends 30) is in; bars 0 and 10 end at 10, 20.
    const times = new Float64Array([0, 10, 20]);
    const at = { times, count: 3, visibleFrom: 25, visibleTo: 35, multiplier: 1 } as const;
    expect(planEviction({ ...at, state: "pressure" }).gpu).toEqual([r(0, 10)]);
    // Window past every bar: all but the last are dropped.
    expect(
      planEviction({ ...at, visibleFrom: 500, visibleTo: 600, state: "pressure" }).gpu,
    ).toEqual([r(0, 10)]);
  });
});

describe("Eviction planner properties (500 seeds each)", { timeout: 60_000 }, () => {
  const SEEDS = Array.from({ length: 500 }, (_, i) => 20261102 + i);

  it("is deterministic: the same input gives a deep-equal plan", () => {
    for (const seed of SEEDS) {
      const a = evictionInput(gen(seed));
      const b = evictionInput(gen(seed));
      expect(planEviction(a), `seed ${seed}`).toEqual(planEviction(b));
    }
  });

  it("never drops a bar inside the window, drops only whole loaded bars, and keeps the visible range", () => {
    for (const seed of SEEDS) {
      const input = evictionInput(gen(seed));
      const w = evictionWindow(input.visibleFrom, input.visibleTo, input.multiplier);
      const plan = planEviction(input);
      for (const range of [...plan.gpu, ...plan.cpu]) {
        const idx = indicesIn(input, range);
        expect(idx.length, `seed ${seed}`).toBeGreaterThan(0);
        expect(input.times[idx[0] as number], `seed ${seed}`).toBe(range.fromTime);
        expect(input.times[idx.at(-1) as number], `seed ${seed}`).toBe(range.toTime);
        for (const i of idx) {
          const t = input.times[i] as number;
          const end = i + 1 < input.count ? (input.times[i + 1] as number) : Infinity;
          const outside = end <= w.fromTime || t > w.toTime;
          expect(outside, `seed ${seed} bar ${i}`).toBe(true);
          expect(t >= input.visibleFrom && t <= input.visibleTo, `seed ${seed}`).toBe(false);
        }
      }
    }
  });

  it("CPU drops only under over, and every CPU drop is within the GPU drops", () => {
    for (const seed of SEEDS) {
      const input = evictionInput(gen(seed));
      const plan = planEviction(input);
      if (input.state !== "over") expect(plan.cpu, `seed ${seed}`).toEqual([]);
      if (input.state === "ok") expect(plan.gpu, `seed ${seed}`).toEqual([]);
      const gpuBars = new Set(plan.gpu.flatMap((g) => indicesIn(input, g)));
      for (const c of plan.cpu) {
        for (const i of indicesIn(input, c)) expect(gpuBars.has(i), `seed ${seed}`).toBe(true);
      }
    }
  });

  it("re-planning after applying a plan drops nothing new (no re-evict of an evicted range)", () => {
    for (const seed of SEEDS) {
      const input = evictionInput(gen(seed), "over");
      const ledger = new EvictionLedger();
      new EvictableRegistry().apply(planEviction(input), ledger);
      const again = planEviction(input, ledger.evicted("gpu"), ledger.evicted("cpu"));
      expect(again, `seed ${seed}`).toEqual({ gpu: [], cpu: [] });
    }
  });
});

describe("EvictableRegistry and EvictionLedger (the registerEvictable seam)", () => {
  it("calls each layer once per range, GPU before CPU, and records the drops", () => {
    const reg = new EvictableRegistry();
    const ledger = new EvictionLedger();
    const calls: string[] = [];
    reg.registerEvictable("candles", (f, t, tier) => calls.push(`candles ${tier} ${f}-${t}`));
    const off = reg.registerEvictable("footprint", (f, t, tier) =>
      calls.push(`fp ${tier} ${f}-${t}`),
    );
    expect(reg.names).toEqual(["candles", "footprint"]);
    expect(reg.apply({ gpu: [r(0, 9)], cpu: [r(0, 9)] }, ledger)).toBe(0);
    expect(calls).toEqual(["candles gpu 0-9", "fp gpu 0-9", "candles cpu 0-9", "fp cpu 0-9"]);
    expect([ledger.evicted("gpu"), ledger.evicted("cpu")]).toEqual([[r(0, 9)], [r(0, 9)]]);
    off();
    off();
    expect(reg.names).toEqual(["candles"]);
  });

  it("a re-registered layer replaces the old one; a throwing layer does not stop the others", () => {
    const reg = new EvictableRegistry();
    const first = vi.fn();
    const second = vi.fn();
    reg.registerEvictable("a", first);
    reg.registerEvictable("a", () => {
      throw new Error("boom");
    });
    reg.registerEvictable("b", second);
    const ledger = new EvictionLedger();
    expect(reg.apply({ gpu: [r(1, 2), r(5, 6)], cpu: [] }, ledger)).toBe(2);
    expect([first.mock.calls.length, second.mock.calls.length]).toEqual([0, 2]);
    // "a" still holds both ranges: neither is recorded, so the planner plans them again.
    expect(ledger.evicted("gpu")).toEqual([]);
  });

  it("only a range every layer dropped is recorded", () => {
    const reg = new EvictableRegistry();
    reg.registerEvictable("a", (f) => {
      if (f === 5) throw new Error("boom");
    });
    const ledger = new EvictionLedger();
    expect(reg.apply({ gpu: [r(1, 2), r(5, 6)], cpu: [] }, ledger)).toBe(1);
    expect(ledger.evicted("gpu")).toEqual([r(1, 2)]);
  });

  it("a partial re-fetch keeps the uncovered remainder; one strictly inside splits the range", () => {
    const ledger = new EvictionLedger();
    ledger.record(r(0, 99), "cpu");
    ledger.restored(50, 99, "cpu");
    expect([ledger.evicted("cpu"), ledger.evicted("gpu")]).toEqual([[r(0, 50)], [r(0, 50)]]);
    ledger.restored(10, 20, "gpu");
    expect([ledger.evicted("cpu"), ledger.evicted("gpu")]).toEqual([
      [r(0, 50)],
      [r(0, 10), r(20, 50)],
    ]);
  });

  it("a CPU drop also records the GPU copy; a re-fetch forgets both, a re-upload the GPU one only", () => {
    const ledger = new EvictionLedger();
    ledger.record(r(20, 29), "cpu");
    ledger.record(r(0, 9), "gpu");
    expect(ledger.evicted("gpu")).toEqual([r(0, 9), r(20, 29)]);
    ledger.record(r(0, 5), "cpu"); // its GPU copy is already covered by [0, 9]
    expect(ledger.evicted("gpu")).toEqual([r(0, 9), r(20, 29)]);
    ledger.restored(0, 9, "gpu");
    expect([ledger.evicted("gpu"), ledger.evicted("cpu")]).toEqual([
      [r(20, 29)],
      [r(0, 5), r(20, 29)],
    ]);
    ledger.restored(20, 29, "cpu");
    expect([ledger.evicted("gpu"), ledger.evicted("cpu")]).toEqual([[], [r(0, 5)]]);
    ledger.clear();
    expect(ledger.evicted("cpu")).toEqual([]);
  });

  it("a just re-fetched range inside the 3x window is not re-evicted on the next sample", () => {
    // Evicted [0, 49] at over; the user pans back to [30, 40] and the range is re-fetched.
    const ledger = new EvictionLedger();
    new EvictableRegistry().apply(planEviction(unit(100, 60, 70, "over")), ledger);
    ledger.restored(0, 49, "cpu");
    const next = planEviction(unit(100, 30, 40, "pressure"), ledger.evicted("gpu"));
    for (const g of next.gpu) expect(g.toTime < 20 || g.fromTime > 50).toBe(true);
    expect(next.gpu).toEqual([r(51, 80), r(0, 19)]); // far edge (the right) first
  });
});
