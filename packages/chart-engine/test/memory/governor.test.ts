// E11-S15 PR-2a: the memory governor (26 §7 State / Response, §3.6 memory tier, §11). Exact
// boundaries (70 % in, 60 % out, 100 % over), one ENGINE_MEMORY_PRESSURE per worsening edge, one
// memoryTier rung per pressure episode (the S15-03 override), GPU out-of-memory -> over, and a
// sample that allocates nothing. The scheduler's masking of the rung is PR-2b (BQ-P2-03).
import { describe, expect, it } from "vitest";
import { probeAllocations } from "../../bench/scenes/memory-sample.js";
import { ENGINE_DRAWING_BUFFER_CLAMPED, ENGINE_MEMORY_PRESSURE } from "../../src/memory/codes.js";
import { MemoryGovernor, OVER_PCT, PRESSURE_PCT, RECOVERY_PCT } from "../../src/memory/Governor.js";
import { gen } from "./gen.js";

const MIB = 2 ** 20;
const BUDGET_MB = 600;
/** Bytes at `pct` % of the 600 MiB budget (exact: 600 MiB is divisible by 100). */
const at = (pct: number): number => (BUDGET_MB * MIB * pct) / 100;

/** Feeds the percentages and returns [state, edge, rung] per sample. */
function run(g: MemoryGovernor, pcts: readonly number[]): [string, boolean, number][] {
  return pcts.map((p) => {
    g.update(at(p));
    return [g.state, g.edge, g.rung];
  });
}

describe("Scenario: memory use crosses the pressure threshold (E11-S15 AC3, governor half)", () => {
  it("the thresholds are the 26 §7 figures and the codes are the §11 names", () => {
    expect([PRESSURE_PCT, RECOVERY_PCT, OVER_PCT]).toEqual([70, 60, 100]);
    expect([ENGINE_MEMORY_PRESSURE, ENGINE_DRAWING_BUFFER_CLAMPED]).toEqual([
      "ENGINE_MEMORY_PRESSURE",
      "ENGINE_DRAWING_BUFFER_CLAMPED",
    ]);
  });

  it("enters pressure at exactly 70 %, not one byte below", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    expect(g.update(at(70) - 1)).toBe("ok");
    expect([g.edge, g.rung, g.tier]).toEqual([false, 0, 0]);
    expect(g.update(at(70))).toBe("pressure");
    expect([g.edge, g.rung, g.tier, g.edges, g.episodes]).toEqual([true, 1, 1, 1, 1]);
  });

  it("stays in pressure at exactly 60 % and returns to ok one byte below it", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    g.update(at(80));
    expect(g.update(at(60))).toBe("pressure");
    expect([g.edge, g.rung]).toEqual([false, 0]);
    expect(g.update(at(60) - 1)).toBe("ok");
    expect([g.edge, g.rung, g.tier]).toEqual([false, -1, 0]);
  });

  it("goes over at exactly 100 %, back to pressure one byte below, raising nothing on recovery", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    expect(run(g, [99.99, 100])).toEqual([
      ["pressure", true, 1],
      ["over", true, 0],
    ]);
    g.update(at(100) - 1);
    expect([g.state, g.edge, g.rung, g.tier]).toEqual(["pressure", false, 0, 1]);
  });

  it("ok -> pressure -> over is two codes and one rung", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    expect(run(g, [50, 75, 110])).toEqual([
      ["ok", false, 0],
      ["pressure", true, 1],
      ["over", true, 0],
    ]);
    expect([g.edges, g.episodes, g.tier]).toEqual([2, 1, 1]);
  });

  it("ok -> over in one sample is one code and one rung", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    expect(run(g, [150])).toEqual([["over", true, 1]]);
    expect([g.edges, g.episodes]).toEqual([1, 1]);
  });

  it("over straight below 60 % returns to ok in one sample: rung reset, no code", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    expect(run(g, [120, 10])).toEqual([
      ["over", true, 1],
      ["ok", false, -1],
    ]);
    expect([g.tier, g.edges]).toEqual([0, 1]);
  });

  it("69/71 % oscillation without a sample below 60 % raises no second code and no second rung", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    run(g, [71, 69, 71, 69, 65, 71, 61, 99]);
    expect([g.state, g.edges, g.episodes, g.tier]).toEqual(["pressure", 1, 1, 1]);
  });

  it("re-arms only below recovery: the next crossing is a new episode, a new rung and a new code", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    const out = run(g, [71, 59, 71]);
    expect(out).toEqual([
      ["pressure", true, 1],
      ["ok", false, -1],
      ["pressure", true, 1],
    ]);
    expect([g.edges, g.episodes]).toEqual([2, 2]);
  });

  it("never per sample: 100 samples at 80 % raise one code and one rung", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    let codes = 0;
    let rungs = 0;
    for (let i = 0; i < 100; i += 1) {
      g.update(at(80));
      if (g.edge) codes += 1;
      if (g.rung === 1) rungs += 1;
    }
    expect([codes, rungs]).toEqual([1, 1]);
  });

  it("masked rung (BQ-P2-03): the governor reports its rung whatever the other tier drivers hold", () => {
    // The governor has no view of zoomTier / loadTier: the rung is reported once per episode and
    // the scheduler (PR-2b) decides whether the effective tier moved and STEPDOWN is raised.
    const g = new MemoryGovernor(BUDGET_MB);
    g.update(at(90));
    expect([g.rung, g.tier]).toEqual([1, 1]);
    g.update(at(95));
    expect([g.rung, g.tier]).toEqual([0, 1]);
  });

  it("ignores a non-finite or negative reading: no state change, no edge", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    g.update(at(80));
    for (const bad of [Number.NaN, Infinity, -Infinity, -1]) {
      expect(g.update(bad)).toBe("pressure");
      expect([g.edge, g.rung]).toEqual([false, 0]);
    }
    expect(g.edges).toBe(1);
  });

  it("refuses a non-positive or non-finite budget", () => {
    for (const bad of [0, -1, Number.NaN, Infinity]) {
      expect(() => new MemoryGovernor(bad)).toThrow(RangeError);
    }
  });

  it("honours the smallest and largest budgets exactly (64 / 4096 MiB)", () => {
    for (const mb of [64, 4096]) {
      const g = new MemoryGovernor(mb);
      expect(g.update((mb * MIB * 70) / 100 - 1)).toBe("ok");
      expect(g.update((mb * MIB * 70) / 100)).toBe("pressure");
      expect(g.update(mb * MIB)).toBe("over");
    }
  });
});

describe("Scenario: GPU out-of-memory moves the governor to over (BQ-S15-14, 26 §11)", () => {
  it("from ok: one code and one rung", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    expect(g.oom()).toBe("over");
    expect([g.edge, g.rung, g.tier, g.edges]).toEqual([true, 1, 1, 1]);
  });

  it("from pressure: one code, no second rung", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    g.update(at(75));
    g.oom();
    expect([g.state, g.edge, g.rung, g.edges, g.episodes]).toEqual(["over", true, 0, 2, 1]);
  });

  it("already over: no code", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    g.update(at(120));
    g.oom();
    expect([g.edge, g.rung, g.edges]).toEqual([false, 0, 1]);
  });

  it("the next sample re-derives the state from usage (a recovery edge raises nothing)", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    g.update(at(30));
    g.oom();
    expect(g.update(at(30))).toBe("ok");
    expect([g.edge, g.rung, g.tier]).toEqual([false, -1, 0]);
    g.oom();
    expect(g.update(at(65))).toBe("pressure");
    expect(g.edge).toBe(false);
  });

  it("OOM -> ok -> OOM: the ok sample closes the episode, so each OOM opens a new rung and code", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    g.oom();
    g.update(at(30)); // below recovery: the episode closes and the rung re-arms
    expect([g.state, g.tier, g.rung, g.edge]).toEqual(["ok", 0, -1, false]);
    g.oom();
    expect([g.state, g.tier, g.rung, g.edge]).toEqual(["over", 1, 1, true]);
    expect([g.edges, g.episodes]).toEqual([2, 2]);
  });
});

describe("Governor sequence property (500 seeds)", { timeout: 60_000 }, () => {
  const SEEDS = Array.from({ length: 500 }, (_, i) => 20261102 + i);
  // Percentages on and around every threshold, plus the open ranges between them.
  const EDGES: readonly number[] = [0, 59, 60, 61, 69, 70, 71, 99, 100, 101, 150];

  it("random sample / OOM sequences hold the rung, edge, re-arm and over invariants", () => {
    // Violations are collected and asserted once: ~50k steps through `expect` would dominate the run.
    const bad: string[] = [];
    const check = (ok: boolean, what: string, ctx: string): void => {
      if (!ok && bad.length < 20) bad.push(`${ctx}: ${what}`);
    };
    for (const seed of SEEDS) {
      const g0 = gen(seed);
      const g = new MemoryGovernor(g0.pick([64, 600, 4096]));
      const bytes = (pct: number): number => (g.budgetMb * MIB * pct) / 100;
      let rungs = 0;
      let openEpisode = false;
      const steps = g0.int(1, 200);
      for (let i = 0; i < steps; i += 1) {
        const prev = g.state;
        const kind = g0.int(0, 19);
        let pct = Number.NaN; // the sample's share; NaN for an OOM or an ignored reading
        if (kind === 0) g.oom();
        else if (kind === 1) g.update(g0.pick([Number.NaN, -1, Infinity]));
        else {
          // Exact thresholds, one byte either side, or anywhere in [0, 160] %.
          const base = kind < 10 ? bytes(g0.pick(EDGES)) : bytes(g0.int(0, 160));
          const used = Math.max(0, base + g0.int(-1, 1));
          pct = (used * 100) / (g.budgetMb * MIB);
          g.update(used);
        }
        const next = g.state;
        const sampled = kind > 1;
        const ctx = `seed ${seed} step ${i} ${prev}->${next} pct ${pct}`;
        // memoryTier is 1 exactly while an episode is open (state is not ok).
        check(g.tier === (next === "ok" ? 0 : 1), "tier follows the episode", ctx);
        // At most one rung per episode: a rung only on leaving ok, never twice in an episode.
        if (g.rung === 1) {
          check(prev === "ok" && !openEpisode, "one rung per episode", ctx);
          openEpisode = true;
          rungs += 1;
        }
        // A pressure code on every worsening edge and only there.
        const worsening = prev !== next && (next === "over" || prev === "ok");
        check(g.edge === worsening, "code only on a worsening edge", ctx);
        // Re-arm (rung -1) only from a sample strictly below 60 %, and every return to ok re-arms.
        if (g.rung === -1) {
          check(prev !== "ok" && sampled && pct < RECOVERY_PCT, "re-arm only below 60 %", ctx);
          openEpisode = false;
        }
        check(!(prev !== "ok" && next === "ok") || g.rung === -1, "ok re-arms", ctx);
        // Hysteresis: a non-ok state holds through any valid sample at or above 60 %.
        if (sampled)
          check(!(prev !== "ok" && pct >= RECOVERY_PCT) || next !== "ok", "holds above 60 %", ctx);
        // A sample is over iff at or above 100 %; ok -> pressure needs at least 70 %.
        if (sampled) check((next === "over") === pct >= OVER_PCT, "over iff >= 100 %", ctx);
        if (prev === "ok" && next === "pressure") {
          check(pct >= PRESSURE_PCT, "pressure from ok needs >= 70 %", ctx);
        }
        if (!sampled && kind === 1) check(prev === next && !g.edge, "bad reading ignored", ctx);
      }
      check(g.episodes === rungs, "episodes equal rungs", `seed ${seed}`);
    }
    expect(bad).toEqual([]);
  });
});

describe("Scenario: a governor sample allocates nothing (C-14.2, rule 31)", () => {
  it("10,000 updates across every state make no counted allocation", () => {
    const g = new MemoryGovernor(BUDGET_MB);
    const pcts = new Float64Array([10, 72, 101, 65, 59, 99, 150, 0]);
    g.update(at(1));
    const calls = probeAllocations(() => {
      for (let i = 0; i < 10_000; i += 1) {
        g.update(at(pcts[i % pcts.length] as number));
        if (i % 777 === 0) g.oom();
      }
    });
    expect(calls).toBe(0);
    expect(g.episodes).toBeGreaterThan(1000);
  });
});
