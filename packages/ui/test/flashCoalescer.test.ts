import { describe, expect, it } from "vitest";
import { createFlashCoalescer, type FlashStart } from "../src/components/index.js";

/** Deterministic 16 ms frame loop over a fake clock; `ticks` are [ms, cell, tick] sorted by ms. */
function run(
  ticks: ReadonlyArray<readonly [number, string, "up" | "down" | "flat" | number]>,
  endMs: number,
  c = createFlashCoalescer(),
): Array<FlashStart & { at: number }> {
  const out: Array<FlashStart & { at: number }> = [];
  let i = 0;
  for (let t = 0; t <= endMs; t += 16) {
    while (i < ticks.length && ticks[i]![0] <= t) {
      const [at, id, tick] = ticks[i]!;
      c.onTick(id, tick, at);
      i += 1;
    }
    for (const s of c.frame(t)) out.push({ ...s, at: t });
  }
  return out;
}

/** A seeded LCG so the mixed-direction runs repeat exactly (the PR 2 fixture replaces this inline). */
function lcg(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

function burst(hz: number, seconds: number, cell = "c"): Array<[number, string, number]> {
  const rnd = lcg(7);
  const out: Array<[number, string, number]> = [];
  for (let t = 0; t < seconds * 1000; t += 1000 / hz) out.push([Math.round(t), cell, rnd() - 0.4]);
  return out;
}

/** The most starts in any half-open 1 000 ms window (MR-1). */
function maxPerSecond(starts: ReadonlyArray<{ at: number }>): number {
  return Math.max(
    0,
    ...starts.map((s) => starts.filter((o) => o.at >= s.at && o.at < s.at + 1000).length),
  );
}

describe("flash coalescer", () => {
  it("flashes every tick of an idle cell at 0.2 Hz, in its own direction", () => {
    const ticks: Array<[number, string, "up" | "down"]> = [
      [0, "c", "up"],
      [5000, "c", "down"],
      [10_000, "c", "up"],
      [15_000, "c", "up"],
    ];
    const starts = run(ticks, 16_000);
    expect(starts.map((s) => s.direction)).toEqual(["up", "down", "up", "up"]);
  });

  it("starts at most one flash per 500 ms and 2 per second under a 40 Hz burst", () => {
    const starts = run(burst(40, 5), 5200);
    expect(starts.length).toBeGreaterThan(5);
    for (let i = 1; i < starts.length; i++) {
      expect(starts[i]!.at - starts[i - 1]!.at).toBeGreaterThanOrEqual(500);
    }
    expect(maxPerSecond(starts)).toBeLessThanOrEqual(2);
  });

  it("keeps below 3 starts a second at any tick rate", () => {
    for (const hz of [1, 2, 3, 5, 10, 25, 40, 100, 250]) {
      expect(maxPerSecond(run(burst(hz, 4), 4200))).toBeLessThanOrEqual(2);
    }
  });

  it("degrades to sustained after 10 s at >= 1 Hz and stops emphasising", () => {
    const c = createFlashCoalescer();
    const starts = run(burst(40, 14), 14_200, c);
    expect(starts.some((s) => s.at < 10_000)).toBe(true);
    expect(starts.filter((s) => s.at >= 10_000)).toEqual([]);
    expect(c.isSustained("c", 13_990)).toBe(true);
  });

  it("treats exactly 1 Hz as busy: sustained after 10 s", () => {
    const starts = run(burst(1, 14), 14_200);
    expect(starts.filter((s) => s.at >= 10_000)).toEqual([]);
    expect(starts.filter((s) => s.at < 10_000).length).toBeGreaterThan(5);
  });

  it("recovers once the cell calms: a gap over 1 s ends the sustained state", () => {
    const c = createFlashCoalescer();
    const busy = burst(20, 12);
    const after: Array<[number, string, "up"]> = [[16_000, "c", "up"]];
    const starts = run([...busy, ...after], 17_000, c);
    expect(starts.filter((s) => s.at >= 10_000 && s.at < 16_000)).toEqual([]);
    expect(starts.filter((s) => s.at >= 12_000).map((s) => s.at)).toEqual([16_000]);
    expect(c.isSustained("c", 16_016)).toBe(false);
  });

  it("decides a window by the net of its ticks, not the last one", () => {
    const c = createFlashCoalescer();
    c.onTick("c", "up", 0);
    expect(c.frame(0)).toEqual([{ cellId: "c", direction: "up" }]);
    c.onTick("c", 3, 100);
    c.onTick("c", -1, 200);
    c.onTick("c", -1, 300);
    c.onTick("c", "down", 400);
    c.onTick("c", "up", 450); // net +1 + ... = 3 - 1 - 1 - 1 + 1 = 1
    expect(c.frame(450)).toEqual([]); // inside the window: nothing queues early
    expect(c.frame(500)).toEqual([{ cellId: "c", direction: "up" }]);
  });

  it("emits nothing for a window whose net is flat", () => {
    const c = createFlashCoalescer();
    c.onTick("c", "up", 0);
    c.frame(0);
    c.onTick("c", 2, 100);
    c.onTick("c", -2, 200);
    expect(c.frame(500)).toEqual([]);
    c.onTick("c", "flat", 600);
    expect(c.frame(600)).toEqual([]);
  });

  it("a net down in the window starts a down flash", () => {
    const c = createFlashCoalescer();
    c.onTick("c", "up", 0);
    c.frame(0);
    c.onTick("c", -5, 100);
    c.onTick("c", 1, 200);
    expect(c.frame(500)).toEqual([{ cellId: "c", direction: "down" }]);
  });

  it("starts at most 20 cells in a frame; the overflow updates without emphasis", () => {
    const c = createFlashCoalescer();
    for (let i = 0; i < 50; i++) c.onTick(`c${i}`, "up", 0);
    const first = c.frame(0);
    expect(first).toHaveLength(20);
    expect(first.map((s) => s.cellId)).toEqual(Array.from({ length: 20 }, (_, i) => `c${i}`));
    expect(c.frame(16)).toEqual([]); // the overflow was dropped, not queued
    c.onTick("c30", "down", 20);
    expect(c.frame(32)).toEqual([{ cellId: "c30", direction: "down" }]);
  });

  it("fills the cap by priority first (focused symbol, open positions)", () => {
    const c = createFlashCoalescer({ maxPerFrame: 2 });
    c.onTick("a", "up", 0);
    c.onTick("b", "up", 0);
    c.onTick("focus", "up", 0, 5);
    c.onTick("pos", "up", 0, 3);
    expect(c.frame(0).map((s) => s.cellId)).toEqual(["focus", "pos"]);
  });

  it("keeps cells independent", () => {
    const starts = run([[0, "b", "down"], ...burst(40, 3, "a")], 3200);
    expect(starts.filter((s) => s.cellId === "b")).toEqual([
      { cellId: "b", direction: "down", at: 0 },
    ]);
  });

  it("forget drops pending state and ignores non-finite deltas", () => {
    const c = createFlashCoalescer();
    c.onTick("c", "up", 0);
    c.forget("c");
    expect(c.frame(0)).toEqual([]);
    expect(c.isSustained("c", 0)).toBe(false);
    c.onTick("c", Number.NaN, 10);
    expect(c.frame(10)).toEqual([]);
  });

  it("prunes quiet cells without changing behaviour", () => {
    const c = createFlashCoalescer();
    c.onTick("c", "up", 0);
    c.frame(0);
    expect(c.frame(20_000)).toEqual([]); // sweep runs
    c.onTick("c", "down", 20_100);
    expect(c.frame(20_100)).toEqual([{ cellId: "c", direction: "down" }]);
  });
  it("is fair under overload: equal-priority cells age-order, every cell starts, none exceeds 2 per second", () => {
    const c = createFlashCoalescer();
    const n = 100;
    const starts = new Map<string, number[]>();
    for (let t = 0; t <= 10_000; t += 16) {
      for (let i = 0; i < n; i++) c.onTick(`c${i}`, "up", t);
      for (const s of c.frame(t)) starts.set(s.cellId, [...(starts.get(s.cellId) ?? []), t]);
    }
    expect(starts.size).toBe(n);
    for (const at of starts.values()) {
      for (const t0 of at)
        expect(at.filter((t) => t >= t0 && t < t0 + 1000).length).toBeLessThanOrEqual(2);
    }
  });

  it("treats a net that cancels to float residue as flat", () => {
    const c = createFlashCoalescer();
    c.onTick("x", "up", 0);
    c.frame(0);
    c.onTick("x", 0.1, 10);
    c.onTick("x", 0.2, 20);
    c.onTick("x", -0.3, 30);
    expect(c.frame(500)).toEqual([]);
    c.onTick("x", 1e-7, 600); // a real tiny move still flashes: the epsilon is relative
    expect(c.frame(1000)).toEqual([{ cellId: "x", direction: "up" }]);
  });
});
